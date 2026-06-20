from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AnomalyFlag:
    system: str
    severity: str  # "warn" | "fail"
    pid: str
    detail: str
    value: float


def _num(values: dict, pid: str) -> float | None:
    v = values.get(pid)
    if v and isinstance(v.get("value"), (int, float)):
        return float(v["value"])
    return None


def evaluate(values: dict, settings) -> list[AnomalyFlag]:
    flags: list[AnomalyFlag] = []
    for pid in ("LONG_FUEL_TRIM_1", "SHORT_FUEL_TRIM_1"):
        val = _num(values, pid)
        if val is not None and abs(val) > settings.diag_fuel_trim_pct:
            cond = "lean" if val > 0 else "rich"
            flags.append(AnomalyFlag("fuel", "warn", pid, f"{pid} {val:+.1f}% ({cond})", val))
    ct = _num(values, "COOLANT_TEMP")
    if ct is not None and ct > settings.diag_coolant_max_c:
        flags.append(AnomalyFlag("cooling", "fail", "COOLANT_TEMP",
                                 f"Coolant temperature {ct:.0f}C exceeds limit", ct))
    return flags


def evaluate_window(samples: list[dict], settings) -> list[AnomalyFlag]:
    flags: list[AnomalyFlag] = []

    o2 = [_num(s["values"], "O2_B1S1") for s in samples]
    o2 = [x for x in o2 if x is not None]
    if len(o2) >= 5 and (max(o2) - min(o2)) < 0.02:
        flags.append(AnomalyFlag("o2", "warn", "O2_B1S1",
                                 f"O2 sensor voltage static at {o2[-1]:.2f}V", o2[-1]))

    rpm = [_num(s["values"], "RPM") for s in samples]
    rpm = [x for x in rpm if x is not None]
    if rpm and max(rpm) <= 1100 and (max(rpm) - min(rpm)) > settings.diag_idle_rpm_jitter:
        swing = max(rpm) - min(rpm)
        flags.append(AnomalyFlag("idle", "warn", "RPM", f"Idle RPM swing {swing:.0f}", swing))

    return flags
