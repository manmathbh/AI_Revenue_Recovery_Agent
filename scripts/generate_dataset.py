#!/usr/bin/env python3
"""Generate the frozen, seeded, ground-truthed synthetic recovery dataset.

Produces two files (both committed to data/):
  * <out>.jsonl              — one Razorpay-shaped webhook body per line
  * <out>.ground_truth.jsonl — one line per case (120), keyed by payment_id

Reproducibility: `random.Random(seed)` + a fixed base timestamp + sort_keys JSON
so the same seed produces byte-identical output. Do NOT change scenario counts
without updating DATASET.md (the frozen spec of record).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

# Scenario mix is fixed by DATASET.md (sums to 120). Order is significant:
# it determines the deterministic RNG draw sequence, so keep it stable.
SCENARIOS: list[tuple[str, int]] = [
    ("S01", 22),  # insufficient funds, good customer
    ("S02", 14),  # network/gateway transient
    ("S03", 12),  # authentication failed / wrong PIN
    ("S04", 10),  # expired/invalid card, no token
    ("S05", 10),  # repeated failure (2 prior attempts)
    ("S06", 8),   # high-value >= INR 25,000
    ("S07", 8),   # bank downtime window
    ("S08", 8),   # self-healed (late auth / user retry)
    ("S09", 8),   # duplicate webhook delivery x2-3
    ("S10", 6),   # unknown/garbled failure
    ("S11", 14),  # low-value stale (>48h old)
]

# Deterministic error-code mapping (mirrors app/domain/diagnosis.py).
# key -> (error_code, error_source, error_step, error_reason, description)
ERROR_PROFILES: dict[str, tuple[str, str, str, str, str]] = {
    "INSUFFICIENT_FUNDS": (
        "BAD_REQUEST_ERROR", "bank", "payment_authorization", "insufficient_funds",
        "The issuing bank declined the payment due to insufficient funds.",
    ),
    "NETWORK_INFRA": (
        "GATEWAY_ERROR", "network", "payment_authorization", "gateway_error",
        "A network error occurred while the gateway processed the payment.",
    ),
    "CUSTOMER_AUTH_REQUIRED": (
        "BAD_REQUEST_ERROR", "customer", "payment_authentication", "authentication_failed",
        "The customer failed authentication (incorrect PIN / OTP timeout).",
    ),
    "INSTRUMENT_INVALID": (
        "BAD_REQUEST_ERROR", "bank", "payment_authorization", "card_expired",
        "The card has expired.",
    ),
    "BANK_DOWNTIME": (
        "GATEWAY_ERROR", "bank", "payment_authorization", "bank_error",
        "The acquiring bank is experiencing an outage.",
    ),
    "UNKNOWN": (
        "UNKNOWN_ERROR", "unknown", "unknown", "unknown_failure",
        "Conflicting failure signals received from the gateway.",
    ),
}

# Ground-truth strategy IDs (bounded catalog S1..S6).
S1 = "S1_IMMEDIATE_RETRY"
S2 = "S2_DELAYED_RETRY"
S3 = "S3_NOTIFY_WITH_LINK"
S5 = "S5_HUMAN_ESCALATION"
S6 = "S6_STOP_RECOVERY"

# Per-scenario ground-truth parameters.
#   diag: diagnosis profile key (or None -> varies)
#   strategy: expected first strategy
#   recoverable / prob: whether + with what probability a recovery action captures
SCENARIO_META: dict[str, dict] = {
    "S01": {"diag": "INSUFFICIENT_FUNDS", "strategy": S2, "prob": 0.65, "token": True,  "method": "card"},
    "S02": {"diag": "NETWORK_INFRA",       "strategy": S1, "prob": 0.80, "token": True,  "method": "card"},
    "S03": {"diag": "CUSTOMER_AUTH_REQUIRED", "strategy": S3, "prob": 0.45, "token": False, "method": "upi"},
    "S04": {"diag": "INSTRUMENT_INVALID",  "strategy": S3, "prob": 0.00, "token": False, "method": "card"},
    "S05": {"diag": None,                  "strategy": S5, "prob": 0.25, "token": True,  "method": "card"},
    "S06": {"diag": None,                  "strategy": S5, "prob": 0.55, "token": True,  "method": "card"},
    "S07": {"diag": "BANK_DOWNTIME",       "strategy": S1, "prob": 0.75, "token": True,  "method": "netbanking"},
    "S08": {"diag": "DUPLICATE_SELF_HEALED", "strategy": S6, "prob": 0.00, "token": False, "method": "upi"},
    "S09": {"diag": "INSUFFICIENT_FUNDS",  "strategy": S2, "prob": 0.65, "token": True,  "method": "card"},
    "S10": {"diag": "UNKNOWN",             "strategy": S5, "prob": 0.00, "token": False, "method": "card"},
    "S11": {"diag": None,                  "strategy": S6, "prob": 0.00, "token": False, "method": "card"},
}

# Diagnosis profiles S05/S06/S11 ("varies") may draw from.
VARIES_DIAGNOSES = ["INSUFFICIENT_FUNDS", "NETWORK_INFRA", "CUSTOMER_AUTH_REQUIRED"]

# Fixed base timestamp (UTC) so output is byte-identical regardless of when generated.
BASE_EPOCH = 1754762400  # 2026-08-20T09:00:00Z
HOUR = 3600

BANKS = ["HDFC", "ICICI", "SBI", "Axis", "Kotak", "Yes"]
CARD_PREFIX = "card_"
FIRST_NAMES = ["Priya", "Aarav", "Meera", "Rohan", "Ananya", "Vikram", "Sneha",
               "Karthik", "Divya", "Aditya", "Pooja", "Rahul", "Neha", "Arjun",
               "Isha", "Sahil", "Riya", "Amit", "Kavya", "Nikhil"]
DOMAINS = ["gmail.com", "yahoo.in", "outlook.com", "hotmail.com"]


def mask_name(name: str) -> str:
    return f"{name[0]}***{name[-1]}"


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[0]}***@{domain}"


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_customer_pool(rng: random.Random, n: int = 60) -> list[dict]:
    pool = []
    for i in range(1, n + 1):
        name = rng.choice(FIRST_NAMES)
        email = f"{name.lower()}{i:03d}@{rng.choice(DOMAINS)}"
        phone = f"+91{rng.randint(7_000_000_000, 9_999_999_999)}"
        tenure_days = rng.randint(30, 1500)
        ltv_minor = int(rng.randint(1_000_00, 20_000_00_00))  # 1k .. 20L in paise
        prior_failures = rng.randint(0, 4)
        prior_recoveries = rng.randint(0, min(3, prior_failures))
        successful = rng.randint(1, 40)
        pool.append({
            "rzp_customer_id": f"cust_{i:04d}",
            "name": name,
            "masked_name": mask_name(name),
            "email": email,
            "email_masked": mask_email(email),
            "contact": phone,
            "contact_hash": sha256_hex(phone),
            "tenure_days": tenure_days,
            "lifetime_value_minor": ltv_minor,
            "prior_failures_90d": prior_failures,
            "prior_recoveries_90d": prior_recoveries,
            "successful_payments": successful,
            "has_saved_token": False,
            "mandate_status": None,
        })
    return pool


def amount_log_uniform(rng: random.Random, lo: float, hi: float) -> int:
    """Log-uniform integer amount (paise) in [lo, hi]."""
    val = math.exp(rng.uniform(math.log(lo), math.log(hi)))
    return max(int(lo), min(int(hi), round(val)))


def build_failed_payment(rng, case_key, payment_id, order_id, customer, diag_key,
                         method, amount_minor, created_at, bank):
    code, source, step, reason, desc = ERROR_PROFILES[diag_key]
    return {
        "id": payment_id,
        "entity": "payment",
        "amount": amount_minor,
        "currency": "INR",
        "status": "failed",
        "order_id": order_id,
        "international": False,
        "method": method,
        "captured": False,
        "email": customer["email"],
        "contact": customer["contact"],
        "bank": bank,
        "card_id": f"{CARD_PREFIX}{case_key.replace('-', '_')}",
        "error_code": code,
        "error_description": desc,
        "error_source": source,
        "error_step": step,
        "error_reason": reason,
        "created_at": created_at,
        "customer_id": customer["rzp_customer_id"],
    }


def build_captured_payment(payment: dict, created_at: int) -> dict:
    out = dict(payment)
    out["status"] = "captured"
    out["captured"] = True
    out["created_at"] = created_at
    for k in ("error_code", "error_description", "error_source", "error_step", "error_reason"):
        out[k] = None
    return out


def webhook_body(event_id: str, event_type: str, payment: dict, created_at: int) -> dict:
    return {
        "id": event_id,
        "entity": "event",
        "account_id": "acc_demo",
        "event": event_type,
        "contains": ["payment"],
        "payload": {"payment": {"entity": payment}},
        "created_at": created_at,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--size", type=int, default=120)
    ap.add_argument("--out", type=str, default="data/dataset_v1.jsonl")
    args = ap.parse_args()

    # Validate size against the frozen scenario mix.
    total = sum(c for _, c in SCENARIOS)
    if args.size != total:
        # Scale proportions but keep order; warn since DATASET.md assumes 120.
        scale = args.size / total
        counts = [(s, max(1, round(c * scale))) for s, c in SCENARIOS]
        diff = args.size - sum(c for _, c in counts)
        idx = 0
        while diff != 0:
            s, c = counts[idx % len(counts)]
            step = 1 if diff > 0 else -1
            counts[idx % len(counts)] = (s, c + step)
            diff -= step
            idx += 1
        print(f"WARNING: size={args.size} != spec 120; scaled scenario counts.")
    else:
        counts = list(SCENARIOS)

    rng = random.Random(args.seed)
    pool = make_customer_pool(rng)

    events: list[dict] = []          # (order, body, case_key, scenario, ground_truth)
    ground_truths: list[dict] = []
    seq = 0

    for scenario, count in counts:
        meta = SCENARIO_META[scenario]
        for n in range(1, count + 1):
            seq += 1
            case_key = f"{scenario}-{n:03d}"
            payment_id = f"pay_{case_key.replace('-', '_')}"
            order_id = f"order_{case_key.replace('-', '_')}"
            event_id = f"evt_{case_key.replace('-', '_')}"

            # Customer: assign from pool; retry scenarios need saved tokens.
            customer = dict(rng.choice(pool))
            customer["has_saved_token"] = meta["token"]
            customer["mandate_status"] = "ACTIVE" if meta["token"] else None

            # Diagnosis profile (may vary).
            diag_key = meta["diag"] if meta["diag"] else rng.choice(VARIES_DIAGNOSES)
            # S08 self-heals: the failed event still carries a real error profile,
            # but ground truth diagnosis is DUPLICATE_SELF_HEALED (captured follows).
            error_profile_key = "NETWORK_INFRA" if diag_key == "DUPLICATE_SELF_HEALED" else diag_key

            # Amount.
            if scenario == "S06":
                # Only S06 crosses the P05 auto-approval ceiling (>= INR 25,000).
                amount_minor = amount_log_uniform(rng, 25_000_00, 2_50_000_00)
            elif scenario == "S11":
                amount_minor = amount_log_uniform(rng, 299_00, 2_000_00)
            else:
                # All other scenarios stay below the P05 ceiling so their
                # ground-truth strategy is not silently overridden by the gate.
                amount_minor = amount_log_uniform(rng, 299_00, 24_999_00)

            # Timestamps (age in hours).
            if scenario == "S11":
                age_hours = rng.randint(48, 70)          # stale, >48h
            elif scenario == "S05":
                age_hours = rng.randint(2, 24)
            else:
                age_hours = rng.randint(0, 24)
            created_at = BASE_EPOCH - age_hours * HOUR - rng.randint(0, 3000)

            # Retry history (S05 = 2 prior recovery attempts).
            prior_attempts = 2 if scenario == "S05" else 0
            customer["prior_failures_90d"] = max(customer["prior_failures_90d"], prior_attempts)

            method = meta["method"]
            bank = rng.choice(BANKS) if method in ("card", "netbanking") else None

            payment = build_failed_payment(
                rng, case_key, payment_id, order_id, customer, error_profile_key,
                method, amount_minor, created_at, bank,
            )

            recoverable = meta["prob"] > 0.0

            gt = {
                "case_key": case_key,
                "scenario": scenario,
                "payment_id": payment_id,
                "order_id": order_id,
                "customer_id": customer["rzp_customer_id"],
                "customer": customer,
                "expected_diagnosis": diag_key,
                "expected_strategy": meta["strategy"],
                "recoverable": recoverable,
                "simulated_capture_probability": meta["prob"],
                "prior_attempts": prior_attempts,
                "notes": f"{scenario} ({meta.get('diag') or 'varies'}, {method})",
            }
            ground_truths.append(gt)

            # Emit failed event.
            events.append((seq, webhook_body(event_id, "payment.failed", payment, created_at),
                           case_key, scenario, gt))

            # S08: append a captured event (late auth / user retry).
            if scenario == "S08":
                capture_ts = created_at + rng.randint(60, 3600)
                cap_payment = build_captured_payment(payment, capture_ts)
                cap_event_id = f"evt_captured_{case_key.replace('-', '_')}"
                events.append((seq, webhook_body(cap_event_id, "payment.captured",
                                                 cap_payment, capture_ts),
                               case_key, scenario, gt))

            # S09: emit duplicate deliveries of the SAME failed event.
            if scenario == "S09":
                for dup in range(1, 3):  # 2 extra deliveries (3 total)
                    events.append((seq, webhook_body(event_id, "payment.failed", payment,
                                                     created_at),
                                   case_key, scenario, gt))

    # Sort events by (order, then captured-after-failed). Stable: failed then captured.
    events.sort(key=lambda e: (e[0], e[1]["event"] == "payment.captured"))
    # Note: sort_key is stable, so same-scenario duplicates stay adjacent and
    # captured follows its failed event. Re-sort to interleave by created_at is
    # NOT done: we keep per-case grouping so the loader can drive S08/S09 correctly.

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w") as fh:
        for _, body, _, _, _ in events:
            fh.write(json.dumps(body, sort_keys=True) + "\n")

    gt_path = out_path.with_name(out_path.stem + ".ground_truth.jsonl")
    with gt_path.open("w") as fh:
        for gt in ground_truths:
            fh.write(json.dumps(gt, sort_keys=True) + "\n")

    # Summary.
    by_scenario: dict[str, int] = {}
    for _, _, _, scenario, _ in events:
        by_scenario[scenario] = by_scenario.get(scenario, 0) + 1
    print(f"seed={args.seed} size={args.size}")
    print(f"events written: {len(events)} -> {out_path}")
    print(f"ground truth written: {len(ground_truths)} cases -> {gt_path}")
    print("scenario case counts:", {s: c for s, c in counts})
    print("event deliveries per scenario:", dict(sorted(by_scenario.items())))
    recoverable = sum(1 for g in ground_truths if g["recoverable"])
    print(f"recoverable cases: {recoverable}/{len(ground_truths)} "
          f"({recoverable / len(ground_truths):.1%})")


if __name__ == "__main__":
    main()
