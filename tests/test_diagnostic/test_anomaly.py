from app.config import Settings
from app.diagnostic.anomaly import AnomalyFlag, evaluate, evaluate_window

S = Settings(_env_file=None)


def _v(**pids):
    return {p: {"value": val, "unit": None} for p, val in pids.items()}


def test_lean_fuel_trim_flags_warn():
    flags = evaluate(_v(LONG_FUEL_TRIM_1=14.0), S)
    assert any(f.system == "fuel" and f.severity == "warn" and "lean" in f.detail for f in flags)


def test_rich_fuel_trim_flags():
    flags = evaluate(_v(SHORT_FUEL_TRIM_1=-13.0), S)
    assert any(f.system == "fuel" and "rich" in f.detail for f in flags)


def test_normal_fuel_trim_no_flag():
    assert evaluate(_v(LONG_FUEL_TRIM_1=3.0, SHORT_FUEL_TRIM_1=-2.0), S) == []


def test_coolant_over_temp_fails():
    flags = evaluate(_v(COOLANT_TEMP=112.0), S)
    assert any(f.system == "cooling" and f.severity == "fail" for f in flags)


def test_missing_pid_is_ignored():
    assert evaluate(_v(RPM=800), S) == []
    assert evaluate({"COOLANT_TEMP": None}, S) == []


def test_window_o2_stuck():
    samples = [{"seq": i, "t": i * 1000, "values": _v(O2_B1S1=0.45)} for i in range(6)]
    flags = evaluate_window(samples, S)
    assert any(f.system == "o2" for f in flags)


def test_window_o2_switching_is_normal():
    vals = [0.1, 0.8, 0.1, 0.8, 0.1, 0.8]
    samples = [{"seq": i, "t": i * 1000, "values": _v(O2_B1S1=vals[i])} for i in range(6)]
    assert not any(f.system == "o2" for f in evaluate_window(samples, S))


def test_window_idle_rpm_jitter():
    rpms = [700, 950, 680, 980, 700]
    samples = [{"seq": i, "t": i * 1000, "values": _v(RPM=rpms[i])} for i in range(5)]
    flags = evaluate_window(samples, S)
    assert any(f.system == "idle" for f in flags)
