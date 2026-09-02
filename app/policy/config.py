"""Policy configuration (GUARDRAILS.md §4) — thresholds are pure data."""

from __future__ import annotations

from dataclasses import dataclass

# Seed defaults (mirrors merchants.policy_config JSONB).
DEFAULT_POLICY_CONFIG: dict = {
    "max_retries": 3,
    "approval_limit_minor": 25_000_00,
    "cooldown_base_min": 30,
    "confidence_floor": 0.60,
    "contact_cap_7d": 3,
    "ttl_hours": 72,
    "simulation_budget": 200,
}


@dataclass(frozen=True)
class PolicyConfig:
    max_retries: int = 3
    approval_limit_minor: int = 25_000_00
    cooldown_base_min: int = 30
    confidence_floor: float = 0.60
    contact_cap_7d: int = 3
    ttl_hours: int = 72
    simulation_budget: int = 200

    @classmethod
    def from_dict(cls, d: dict | None) -> PolicyConfig:
        d = d or {}
        merged = {**DEFAULT_POLICY_CONFIG, **d}
        return cls(**merged)

    def to_dict(self) -> dict:
        return {
            "max_retries": self.max_retries,
            "approval_limit_minor": self.approval_limit_minor,
            "cooldown_base_min": self.cooldown_base_min,
            "confidence_floor": self.confidence_floor,
            "contact_cap_7d": self.contact_cap_7d,
            "ttl_hours": self.ttl_hours,
            "simulation_budget": self.simulation_budget,
        }


# Rules whose failure produces ESCALATE (route to human approval).
ESCALATE_RULES = frozenset({"P05", "P06"})

# Rules whose failure produces WAIT (re-schedule).
WAIT_RULES = frozenset({"P04", "P09"})

# All other failing rules produce BLOCK (fallback path).
