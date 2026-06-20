from app.config import Settings
from app.telemetry.pids import CURATED_PIDS


def test_live_settings_defaults():
    s = Settings(_env_file=None)
    assert s.live_sample_hz == 1.0
    assert s.live_min_interval_s == 0.25
    assert s.live_max_pids == 16
    assert s.live_subscriber_queue == 2
    assert s.live_recorder_batch == 20


def test_curated_pids_are_canonical_names():
    assert "RPM" in CURATED_PIDS
    assert "SPEED" in CURATED_PIDS
    assert "COOLANT_TEMP" in CURATED_PIDS
    # all entries are non-empty upper-case python-OBD command names
    assert all(p == p.upper() and p for p in CURATED_PIDS)
    assert len(CURATED_PIDS) == len(set(CURATED_PIDS))  # no dupes
