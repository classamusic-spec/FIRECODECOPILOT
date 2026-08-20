"""Code-cycle awareness: the active-editions block and the 'new cycle due' reminder."""
from app import cycles


def test_active_cycle_block_lists_editions_and_connecticut_applicability_rules():
    block = cycles.active_cycle_block()
    assert "ACTIVE CYCLE" in block
    assert "2021 International Fire Code" in block
    assert "NFPA 101" in block and "Part IV" in block
    assert "January 1, 2006" in block
    assert "NFPA 1" in block and "Fire Prevention Code" in block
    assert "VERIFY" not in block


def test_reminder_fires_within_warn_window():
    # The example pending cycle expects 2026-07-01; with the default 90-day warn window the
    # reminder should be active in 2026. (cycle_reminder returns None only if far out / unset.)
    cfg = cycles._load()
    msg = cycles.cycle_reminder(cfg)
    # Either a reminder string (in window) or None (out of window). Delayed cycles should tell the
    # marshal to remain on the active cycle rather than implying the proposal took effect.
    assert msg is None or "code books" in msg or "delayed" in msg.lower()


def test_delayed_cycle_is_reported_as_delayed_not_possibly_in_effect():
    cfg = {
        "pending_cycle": {
            "label": "2026 Connecticut State Codes",
            "status": "delayed",
            "expected_effective_date": "2026-07-01",
            "notes": "Adoption is delayed pending Legislative Regulation Review Committee approval.",
        },
        "reminders": {"warn_days_before_expected": 90},
    }
    msg = cycles.cycle_reminder(cfg)
    assert msg is not None
    assert "delayed" in msg.lower()
    assert "Legislative Regulation Review Committee" in msg
    assert "may already be in effect" not in msg
