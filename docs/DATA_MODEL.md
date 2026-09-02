# DATA_MODEL.md — PostgreSQL schema

## 1. ER overview

```
merchants 1───* customers 1───* payments
                                  │ 1
                                  │
                                  ▼ *
                            recovery_cases 1───* agent_decisions
                                  │ 1          1───* policy_decisions
                                  │            1───* recovery_actions 1───* notifications
                                  │ 1          1───* escalations
                                  ├────────────┴──* audit_events (polymorphic: case_id)
webhook_events (standalone idempotency ledger)     eval_runs 1───* eval_case_results
```

13 tables. Conventions: `id` UUID v7 (time-ordered) PK unless noted; `created_at`/`updated_at` timestamptz NOT NULL DEFAULT now(); money as BIGINT **paise**; enums as PG ENUM types; soft-delete nowhere (audit requires immutability).

## 2. Tables

### merchants
| column | type | notes |
|---|---|---|
| id | UUID PK | |
| name | TEXT NOT NULL | demo merchant "CloudKart" |
| rzp_key_id | TEXT NOT NULL UNIQUE | test key id (secret lives in env/vault, never DB) |
| policy_config | JSONB NOT NULL | thresholds snapshot (max_retries=3, approval_limit_minor=25_000_00, cooldown_base_min=30, confidence_floor=0.60, contact_cap_7d=3, ttl_hours=72) |

### customers
| column | type | notes |
|---|---|---|
| id | UUID PK | |
| merchant_id | UUID FK→merchants | |
| rzp_customer_id | TEXT UNIQUE | `cust_...` when real |
| masked_name | TEXT NOT NULL | `P***a` — full name never stored |
| contact_hash | TEXT NOT NULL | sha256(phone); dedupe key |
| email_masked | TEXT | `p***@x.com` |
| tenure_days, lifetime_value_minor | INT, BIGINT | aggregates refreshed on events |
| prior_failures_90d, prior_recoveries_90d, successful_payments | INT DEFAULT 0 | |
| has_saved_token / mandate_status | BOOL / TEXT NULL | drives retry eligibility |

Indexes: `(merchant_id, contact_hash)` UNIQUE.

### payments (mirror of Razorpay payment entities)
| column | type | notes |
|---|---|---|
| id | UUID PK | |
| merchant_id | UUID FK | |
| customer_id | UUID FK NULL | |
| rzp_payment_id | TEXT UNIQUE NOT NULL | `pay_...` |
| rzp_order_id | TEXT INDEX | `order_...` groups attempts |
| status | ENUM(created,authorized,captured,failed) | mirrored from source of truth only |
| amount_minor, currency | BIGINT, CHAR(3) | |
| method | TEXT | card/upi/netbanking/wallet |
| error_code, error_source, error_step, error_reason, error_description | TEXT NULL | from webhook payload |
| bank, card_last4 | TEXT NULL | |
| is_simulated | BOOL DEFAULT false | true for synthetic dataset rows |
| rzp_created_at | TIMESTAMPTZ | entity time |

### recovery_cases
| column | type | notes |
|---|---|---|
| id | UUID PK | |
| case_ref | TEXT UNIQUE NOT NULL | human ID `RC-000123` (sequence) |
| merchant_id, payment_id, customer_id | UUID FKs | payment_id UNIQUE → one case per failed payment |
| status | ENUM(DETECTED,ANALYZING,DIAGNOSED,PLANNED,POLICY_CHECK,AWAITING_APPROVAL,APPROVED,EXECUTING,VERIFYING,RECOVERED,CLOSED_UNRECOVERED,BLOCKED,ESCALATED,EXPIRED,CANCELLED,FAILED) NOT NULL | FSM-guarded |
| risk_score SMALLINT CHECK 0–100, risk_band ENUM(CRITICAL,HIGH,MEDIUM,LOW) | | |
| diagnosis_class ENUM(INSUFFICIENT_FUNDS,CUSTOMER_AUTH_REQUIRED,INSTRUMENT_INVALID,NETWORK_INFRA,BANK_DOWNTIME,DUPLICATE_SELF_HEALED,UNKNOWN) NULL | | |
| strategy_id TEXT NULL, agent_confidence NUMERIC(3,2) NULL | | latest proposal |
| retry_count SMALLINT DEFAULT 0 | | consumed retry budget |
| last_attempt_at TIMESTAMPTZ NULL | | cooldown anchor |
| recovered_amount_minor BIGINT DEFAULT 0 | | written ONLY by verification svc |
| outcome ENUM(RECOVERED,SELF_HEALED,UNRECOVERED,...) NULL; closed_at, sla_deadline_at | | |
| ground_truth JSONB NULL | | dataset labels for eval accuracy |

Indexes: `(status)` partial WHERE status IN active-states (worker claim), `(risk_band, sla_deadline_at)`, `(merchant_id, created_at)`.

### agent_decisions
| column | type | notes |
|---|---|---|
| id UUID PK; case_id FK; decision_ref TEXT UNIQUE (`DEC-...`) | | |
| origin ENUM(LLM,FALLBACK) ; model TEXT NULL; prompt_tokens, completion_tokens INT NULL | | cost accounting |
| diagnosis_class, diagnosis_confidence, strategy_id, strategy_confidence | | validated DecisionRecord |
| params JSONB ; rationale TEXT(≤400) | | |
| reasoning_trace JSONB | | tool calls + observations (scratchpad) |
| iterations_used SMALLINT ; latency_ms INT | | bounded-loop evidence |

### policy_decisions
| column | type | notes |
|---|---|---|
| id UUID PK; case_id FK; decision_id FK→agent_decisions NULL | | |
| proposed_action TEXT ; verdict ENUM(ALLOW,BLOCK,ESCALATE,WAIT) | | |
| rule_results JSONB NOT NULL | | ordered [{rule_id, passed, reason}] — full trace even on short-circuit |
| config_snapshot JSONB | | thresholds used (reproducibility) |

Index: `(case_id, created_at)`.

### recovery_actions
| column | type | notes |
|---|---|---|
| id UUID PK; action_ref TEXT UNIQUE (`ACT-...`); case_id FK | | |
| action_type ENUM(RETRY_CHARGE,SEND_RECOVERY_LINK,NOTIFY_CUSTOMER,CREATE_ESCALATION) | | |
| attempt_no SMALLINT NOT NULL | | |
| idempotency_key TEXT NOT NULL | | `sha256(case_id+action_type+attempt_no)` |
| execution_mode ENUM(REAL_RZP,SIMULATED,OUTBOX) NOT NULL | | honesty label surfaced in UI |
| gateway_ref TEXT NULL | | `plink_...` / simulated txn id |
| status ENUM(PENDING,GATED,EXECUTING,SUCCEEDED,FAILED,SUPERSEDED) | | |
| result JSONB NULL ; error TEXT NULL ; executed_at TIMESTAMPTZ NULL | | |

Constraints: `UNIQUE(case_id, action_type, attempt_no)` ← duplicate-action impossibility; `UNIQUE(idempotency_key)`.

### notifications (outbox)
id PK; case_id FK; action_id FK; channel ENUM(SMS,EMAIL) ; rendered_subject/rendered_body TEXT ; status ENUM(QUEUED,SIMULATED_SENT,SUPPRESSED) ; suppressed_reason TEXT (e.g., P08 contact cap).

### escalations
id PK; escalation_ref UNIQUE (`ESC-...`); case_id FK; reason_code ENUM(MAX_RETRIES_EXHAUSTED,AMOUNT_CEILING,LOW_CONFIDENCE,UNKNOWN_DIAGNOSIS,EXECUTOR_ERROR,POLICY_DOUBLE_BLOCK) ; note TEXT ; status ENUM(OPEN,APPROVED,REJECTED,EXPIRED) ; decided_by, decision_note, decided_at.

### webhook_events (idempotency ledger)
| column | type | notes |
|---|---|---|
| id UUID PK | | |
| provider TEXT DEFAULT 'razorpay' ; event_id TEXT NOT NULL UNIQUE | | Razorpay event id or sha256(raw body) fallback — duplicate delivery dies here |
| event_type TEXT ; signature_valid BOOL ; payload JSONB ; received_at | | raw payload retained for replay/audit |

### audit_events (append-only)
id UUID PK; case_id FK NULL; actor ENUM(SYSTEM,AGENT,POLICY,EXECUTOR,VERIFIER,HUMAN) ; event_type TEXT (CASE_CREATED, STATE_TRANSITION, DECISION_RECORDED, POLICY_EVALUATED, ACTION_EXECUTED, WEBHOOK_RECEIVED, ESCALATION_DECIDED, METRICS_FINALIZED…) ; detail JSONB ; prev_event_hash, event_hash TEXT — hash-chained per case (tamper-evidence). NO UPDATE/DELETE grants.

### eval_runs / eval_case_results
run: id PK; run_ref UNIQUE; dataset_seed INT; started/finished; config_snapshot JSONB; report JSONB (final metrics).
results: run_id FK; case_id FK; expected_diagnosis, actual_diagnosis, expected_strategy, actual_strategy, outcome, recovered_amount_minor; UNIQUE(run_id, case_id).

## 3. Consistency mechanics

- Webhook ingest tx: INSERT webhook_events (unique event_id) → upsert customer/payment → INSERT case + audit row. Duplicate ⇒ conflict ⇒ 200-OK no-op.
- Worker claim: `UPDATE ... SET status='ANALYZING' WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED ...) RETURNING *`.
- Action exec tx: INSERT recovery_action (unique constraints) → transition case → commit → THEN call gateway; crash between commit and gateway call leaves PENDING action reconciled by sweeper (gateway_ref lookup by idempotency metadata where supported).
- All timestamps timestamptz UTC; Alembic migration per change.
