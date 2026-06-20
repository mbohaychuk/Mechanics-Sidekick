from app.config import Settings


def test_diagnostic_settings_defaults():
    s = Settings(_env_file=None)
    assert s.diag_enabled is True
    assert s.diag_protocol == "default"
    assert s.diag_commentary_interval_s == 5.0
    assert s.diag_commentary_max_tokens == 160
    assert s.diag_commentary_window_s == 15.0
    assert s.diag_commentary_max_points == 20
    assert s.diag_max_adhoc_steps == 2
    assert s.diag_fuel_trim_pct == 10.0
    assert s.diag_coolant_max_c == 105.0
    assert s.diag_idle_rpm_jitter == 150.0
    assert s.diag_manual_min_score == 0.35
    assert s.diag_report_recent_limit == 3
    assert s.diag_report_max_tokens == 600
