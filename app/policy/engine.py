"""Policy engine: ordered, deterministic, pure rule evaluator (GUARDRAILS.md §1).

"The LLM proposes. The policy engine disposes." No network calls, no LLM, no
inline clock reads (time is injected via PolicyContext.now).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.enums import PolicyVerdict
from app.policy.config import ESCALATE_RULES, WAIT_RULES, PolicyConfig
from app.policy.rules import RULE_ORDER, PolicyContext, RuleHit


@dataclass(frozen=True)
class PolicyResult:
    verdict: PolicyVerdict
    rule_results: list[dict]
    triggered_rule_id: str | None
    config_snapshot: dict


def evaluate(ctx: PolicyContext) -> PolicyResult:
    """Run all rules in fixed order; short-circuit on first hard fail.

    Rules after the failing one are recorded as skipped (evaluated=False) so the
    audit trace is complete regardless of short-circuiting.
    """
    hits: list[RuleHit] = []
    failed_rule_id: str | None = None

    for rule_id, fn in RULE_ORDER:
        if failed_rule_id is not None:
            hits.append(RuleHit(rule_id, True, "skipped (short-circuit)", evaluated=False))
            continue
        hit = fn(ctx)  # type: ignore[operator]
        hits.append(hit)
        if not hit.passed:
            failed_rule_id = rule_id

    if failed_rule_id is None:
        verdict = PolicyVerdict.ALLOW
    elif failed_rule_id in ESCALATE_RULES:
        verdict = PolicyVerdict.ESCALATE
    elif failed_rule_id in WAIT_RULES:
        verdict = PolicyVerdict.WAIT
    else:
        verdict = PolicyVerdict.BLOCK

    rule_results = [
        {"rule_id": h.rule_id, "passed": h.passed, "reason": h.reason, "evaluated": h.evaluated}
        for h in hits
    ]
    return PolicyResult(
        verdict=verdict,
        rule_results=rule_results,
        triggered_rule_id=failed_rule_id,
        config_snapshot=PolicyConfig.to_dict(ctx.config),
    )
