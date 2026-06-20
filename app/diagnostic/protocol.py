from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepTarget:
    pid: str
    low: float | None = None
    high: float | None = None

    def in_range(self, value: float) -> bool:
        if self.low is not None and value < self.low:
            return False
        if self.high is not None and value > self.high:
            return False
        return True


@dataclass
class Step:
    id: str
    label: str
    instruction: str
    target: StepTarget | None = None
    capture_pids: list[str] = field(default_factory=list)
    min_dwell_s: float = 5.0
    timeout_s: float = 60.0
    adhoc: bool = False


@dataclass
class DiagnosticProtocol:
    name: str
    steps: list[Step]


@dataclass
class StepState:
    index: int
    total: int
    step: Step
    state: str  # "active" | "done" | "skipped"
    seq_start: int | None = None
    seq_end: int | None = None


_FUEL = ["SHORT_FUEL_TRIM_1", "LONG_FUEL_TRIM_1"]

DEFAULT_PROTOCOL = DiagnosticProtocol(
    name="default",
    steps=[
        Step(id="idle_baseline", label="Idle baseline",
             instruction="Let the engine idle without touching the throttle.",
             target=StepTarget("RPM", 550, 1000),
             capture_pids=["RPM", "COOLANT_TEMP", *_FUEL], min_dwell_s=15.0, timeout_s=45.0),
        Step(id="warm_up", label="Warm up",
             instruction="Keep idling until the engine reaches operating temperature.",
             target=StepTarget("COOLANT_TEMP", 80, 105),
             capture_pids=["COOLANT_TEMP", "RPM"], min_dwell_s=5.0, timeout_s=120.0),
        Step(id="rev_2500", label="Rev to 2500",
             instruction="Hold the engine at about 2500 rpm.",
             target=StepTarget("RPM", 2300, 2700),
             capture_pids=["RPM", "MAF", "TIMING_ADVANCE", *_FUEL, "O2_B1S1"],
             min_dwell_s=8.0, timeout_s=45.0),
        Step(id="return_idle", label="Return to idle",
             instruction="Let the engine settle back to idle.",
             target=StepTarget("RPM", 550, 1000),
             capture_pids=["RPM", *_FUEL], min_dwell_s=10.0, timeout_s=45.0),
        Step(id="steady_cruise", label="Steady cruise (optional)",
             instruction="If driving, hold a steady 50-70 km/h. Skipped automatically on a stationary test.",
             target=StepTarget("SPEED", 50, 70),
             capture_pids=["SPEED", "RPM", "MAF", *_FUEL], min_dwell_s=20.0, timeout_s=30.0),
    ],
)

_PROTOCOLS = {DEFAULT_PROTOCOL.name: DEFAULT_PROTOCOL}


def get_protocol(name: str) -> DiagnosticProtocol:
    return _PROTOCOLS.get(name, DEFAULT_PROTOCOL)


ADHOC_PID_LIMITS = {"RPM": (0.0, 4000.0), "SPEED": (0.0, 120.0), "COOLANT_TEMP": (0.0, 110.0)}


def safe_adhoc_step(directive: object) -> Step | None:
    """Validate an LLM 'adapt' directive into a bounded, safe ad-hoc Step, or None."""
    if not isinstance(directive, dict) or directive.get("action") != "insert":
        return None
    step = directive.get("step")
    if not isinstance(step, dict):
        return None
    pid = step.get("pid")
    if pid not in ADHOC_PID_LIMITS:
        return None
    lo_lim, hi_lim = ADHOC_PID_LIMITS[pid]
    low, high = step.get("low"), step.get("high")
    for bound in (low, high):
        if bound is not None:
            try:
                if not (lo_lim <= float(bound) <= hi_lim):
                    return None
            except (TypeError, ValueError):
                return None
    label = str(step.get("label") or f"Hold {pid}")[:80]
    instruction = str(step.get("instruction") or f"Hold {pid} in range.")[:200]
    return Step(
        id=f"adhoc_{pid.lower()}", label=label, instruction=instruction,
        target=StepTarget(pid=pid, low=low, high=high),
        capture_pids=[pid], min_dwell_s=5.0, timeout_s=45.0, adhoc=True,
    )


def _num(values: dict, pid: str) -> float | None:
    v = values.get(pid)
    if v and isinstance(v.get("value"), (int, float)):
        return float(v["value"])
    return None


class ProtocolRunner:
    def __init__(self, protocol: DiagnosticProtocol, max_adhoc: int) -> None:
        self._steps: list[Step] = list(protocol.steps)
        self._max_adhoc = max_adhoc
        self._adhoc_used = 0
        self._idx = 0
        self._dwell_start_ms: int | None = None
        self._step_start_ms: int | None = None
        self._seq_start: int | None = None
        self._last_seq: int = 0
        self.completed: list[StepState] = []

    @property
    def total(self) -> int:
        return len(self._steps)

    def is_complete(self) -> bool:
        return self._idx >= len(self._steps)

    def current(self) -> StepState | None:
        if self.is_complete():
            return None
        return StepState(index=self._idx, total=len(self._steps),
                         step=self._steps[self._idx], state="active")

    def offer(self, values: dict, seq: int, t_ms: int) -> StepState | None:
        if self.is_complete():
            return None
        self._last_seq = seq
        step = self._steps[self._idx]
        if self._step_start_ms is None:
            self._step_start_ms = t_ms
            self._seq_start = seq

        if step.target is None:
            if t_ms - self._step_start_ms >= step.timeout_s * 1000:
                return self._complete(seq, "done")
            return None

        val = _num(values, step.target.pid)
        if val is not None and step.target.in_range(val):
            if self._dwell_start_ms is None:
                self._dwell_start_ms = t_ms
            if t_ms - self._dwell_start_ms >= step.min_dwell_s * 1000:
                return self._complete(seq, "done")
        else:
            self._dwell_start_ms = None

        if t_ms - self._step_start_ms >= step.timeout_s * 1000:
            return self._complete(seq, "skipped")
        return None

    def skip(self) -> StepState | None:
        if self.is_complete():
            return None
        return self._complete(self._last_seq, "skipped")

    def insert_adhoc(self, step: Step) -> bool:
        if self._adhoc_used >= self._max_adhoc:
            return False
        self._adhoc_used += 1
        self._steps.insert(self._idx + 1, step)
        return True

    def _complete(self, seq: int, state: str) -> StepState:
        st = StepState(index=self._idx, total=len(self._steps), step=self._steps[self._idx],
                       state=state, seq_start=self._seq_start, seq_end=seq)
        self.completed.append(st)
        self._idx += 1
        self._dwell_start_ms = None
        self._step_start_ms = None
        self._seq_start = None
        return st
