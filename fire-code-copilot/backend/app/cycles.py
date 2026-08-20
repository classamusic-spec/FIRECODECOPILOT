"""Reads config/code_cycles.yaml: builds the active-editions block injected into the agent
prompt, and computes whether a 'new code cycle due' reminder should fire."""
from __future__ import annotations
from datetime import date, datetime
from pathlib import Path
import yaml
from .settings import settings


def _load() -> dict:
    """Load the local cycle config; fall back to the committed authoritative example so a fresh
    installation has the same adopted-code applicability guidance."""
    path = Path(settings.code_cycles_config)
    if not path.exists():
        example = path.with_name("code_cycles.example.yaml")
        if example.exists():
            path = example
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def active_cycle_block() -> str:
    """Human-readable list of the adopted editions, for the system prompt."""
    cfg = _load()
    act = cfg.get("active_cycle", {})
    lines = [f"ACTIVE CYCLE: {act.get('label','(unset)')} (effective {act.get('effective_date','?')})"]
    for d in act.get("documents", []):
        lines.append(f"  - {d.get('title')} — CT edition {d.get('ct_edition')} "
                     f"(base: {d.get('base_model_code','?')})")
        if d.get("applies_to"):
            lines.append(f"    Applies to: {d['applies_to']}")
    rules = act.get("applicability_rules") or []
    if rules:
        lines.append("  Connecticut applicability rules:")
        lines.extend(f"    - {rule}" for rule in rules)
    warn = cycle_reminder(cfg)
    if warn:
        lines.append(f"  ⚠️ {warn}")
    return "\n".join(lines)


def cycle_reminder(cfg: dict | None = None) -> str | None:
    """Return a warning string if a new cycle is imminent/overdue, else None."""
    cfg = cfg or _load()
    pend = cfg.get("pending_cycle") or {}
    if str(pend.get("status", "")).lower() == "delayed":
        note = str(pend.get("notes") or "").strip()
        if note:
            return f"{pend.get('label','New cycle')} is delayed. {note}"
        return (f"{pend.get('label','New cycle')} is delayed pending state approval. Continue using "
                "the active code cycle until CT DAS publishes an approved effective date; then "
                "update the code books + config/code_cycles.yaml and re-run ingestion.")
    exp = pend.get("expected_effective_date")
    if not exp:
        return None
    try:
        exp_d = datetime.strptime(exp, "%Y-%m-%d").date()
    except ValueError:
        return None
    warn_days = (cfg.get("reminders", {}) or {}).get("warn_days_before_expected", 90)
    days_out = (exp_d - date.today()).days
    if days_out <= warn_days:
        when = "may already be in effect" if days_out < 0 else f"expected in ~{days_out} days"
        return (f"{pend.get('label','New cycle')} {when}. Verify with CT DAS, update your "
                f"code books + config/code_cycles.yaml, then re-run ingestion.")
    return None
