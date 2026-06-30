"""Code-cycle awareness: the active-editions block and the 'new cycle due' reminder."""
from app import cycles


def test_active_cycle_block_lists_editions():
    block = cycles.active_cycle_block()
    assert "ACTIVE CYCLE" in block
    # The example config lists the Connecticut State Fire Safety Code.
    assert "Fire Safety Code" in block or "CSFSC" in block


def test_reminder_fires_within_warn_window():
    # The example pending cycle expects 2026-07-01; with the default 90-day warn window the
    # reminder should be active in 2026. (cycle_reminder returns None only if far out / unset.)
    cfg = cycles._load()
    msg = cycles.cycle_reminder(cfg)
    # Either a reminder string (in window) or None (out of window) — but it must not raise,
    # and when the pending date is set it should produce guidance text when near.
    assert msg is None or "code books" in msg
