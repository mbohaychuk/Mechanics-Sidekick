from app.diagnostic.protocol import (
    DEFAULT_PROTOCOL,
    DiagnosticProtocol,
    ProtocolRunner,
    Step,
    StepTarget,
    get_protocol,
    safe_adhoc_step,
)


def _sample(pid, value):
    return {pid: {"value": value, "unit": None}}


def DiagnosticProtocol_single(step):
    return DiagnosticProtocol(name="t", steps=[step])


def test_default_protocol_has_expected_step_ids():
    ids = [s.id for s in DEFAULT_PROTOCOL.steps]
    assert ids == ["idle_baseline", "warm_up", "rev_2500", "return_idle", "steady_cruise"]
    assert get_protocol("default") is DEFAULT_PROTOCOL
    assert get_protocol("unknown") is DEFAULT_PROTOCOL  # falls back


def test_idle_steps_have_no_floor_and_rev_is_floor_only():
    steps = {s.id: s for s in DEFAULT_PROTOCOL.steps}
    # An idle has no minimum — any low rpm counts as idle, only an upper bound matters.
    for sid in ("idle_baseline", "return_idle"):
        t = steps[sid].target
        assert t.pid == "RPM" and t.low is None and t.high is not None
        assert t.in_range(520) and t.in_range(700) and not t.in_range(2500)
    # Rev: just get it above the floor; no range to fuss over holding within.
    rev = steps["rev_2500"].target
    assert rev.pid == "RPM" and rev.low == 2000 and rev.high is None
    assert rev.in_range(2100) and rev.in_range(3200) and not rev.in_range(1500)


def test_target_in_range():
    t = StepTarget(pid="RPM", low=2300, high=2700)
    assert t.in_range(2500)
    assert not t.in_range(2200)
    assert not t.in_range(2800)


def test_step_completes_only_after_dwell_holds():
    step = Step(id="rev", label="Rev", instruction="rev", target=StepTarget("RPM", 2300, 2700),
                min_dwell_s=2.0, timeout_s=30.0)
    runner = ProtocolRunner(DiagnosticProtocol_single(step), max_adhoc=0)
    # in range at t=0, still dwelling at t=1000 (< 2s) → no completion
    assert runner.offer(_sample("RPM", 2500), seq=1, t_ms=0) is None
    assert runner.offer(_sample("RPM", 2500), seq=2, t_ms=1000) is None
    # at t=2000 the 2s dwell is satisfied → completes with seq_start=1, seq_end=3
    done = runner.offer(_sample("RPM", 2500), seq=3, t_ms=2000)
    assert done is not None and done.state == "done"
    assert done.seq_start == 1 and done.seq_end == 3
    assert runner.is_complete()


def test_out_of_range_resets_dwell():
    step = Step(id="rev", label="Rev", instruction="rev", target=StepTarget("RPM", 2300, 2700),
                min_dwell_s=2.0, timeout_s=30.0)
    runner = ProtocolRunner(DiagnosticProtocol_single(step), max_adhoc=0)
    assert runner.offer(_sample("RPM", 2500), seq=1, t_ms=0) is None
    assert runner.offer(_sample("RPM", 1000), seq=2, t_ms=1000) is None  # drops out → reset
    assert runner.offer(_sample("RPM", 2500), seq=3, t_ms=1500) is None  # dwell restarts at 1500
    assert runner.offer(_sample("RPM", 2500), seq=4, t_ms=3000) is None  # only 1.5s held
    done = runner.offer(_sample("RPM", 2500), seq=5, t_ms=3500)  # 2s since 1500
    assert done is not None and done.state == "done"


def test_step_times_out_to_skipped():
    step = Step(id="cruise", label="Cruise", instruction="drive", target=StepTarget("SPEED", 50, 70),
                min_dwell_s=2.0, timeout_s=5.0)
    runner = ProtocolRunner(DiagnosticProtocol_single(step), max_adhoc=0)
    assert runner.offer(_sample("SPEED", 0), seq=1, t_ms=0) is None
    done = runner.offer(_sample("SPEED", 0), seq=2, t_ms=5000)  # never in range, timeout
    assert done is not None and done.state == "skipped"


def test_skip_advances_current_step():
    runner = ProtocolRunner(DEFAULT_PROTOCOL, max_adhoc=0)
    runner.offer(_sample("RPM", 700), seq=1, t_ms=0)
    st = runner.skip()
    assert st is not None and st.state == "skipped" and st.index == 0
    assert runner.current().index == 1


def test_insert_adhoc_respects_cap():
    runner = ProtocolRunner(DEFAULT_PROTOCOL, max_adhoc=1)
    adhoc = Step(id="adhoc_rpm", label="Hold 2000", instruction="hold 2000",
                 target=StepTarget("RPM", 1900, 2100), adhoc=True)
    assert runner.insert_adhoc(adhoc) is True
    assert runner.insert_adhoc(adhoc) is False  # cap reached
    # inserted right after the current (index 0) step
    assert runner._steps[1].id == "adhoc_rpm"


def test_safe_adhoc_step_validates_vocabulary_and_bounds():
    ok = safe_adhoc_step({"action": "insert", "step": {"pid": "RPM", "low": 1900, "high": 2100,
                                                       "label": "Hold 2000", "instruction": "hold"}})
    assert ok is not None and ok.target.pid == "RPM" and ok.adhoc is True

    assert safe_adhoc_step({"action": "insert", "step": {"pid": "BOOST", "low": 1, "high": 2}}) is None
    assert safe_adhoc_step({"action": "insert", "step": {"pid": "RPM", "low": 0, "high": 9000}}) is None
    assert safe_adhoc_step({"action": "skip"}) is None  # not an insert
    assert safe_adhoc_step("nonsense") is None


def test_safe_adhoc_step_rejects_non_numeric_bound():
    # A malformed LLM directive with a string bound must return None, not raise ValueError.
    assert safe_adhoc_step({"action": "insert", "step": {"pid": "RPM", "low": "abc"}}) is None


def test_progress_reports_live_value_target_and_dwell():
    # The guided-coach UI needs per-sample status: where the value is vs the target band,
    # whether it's in range, and how much of the required dwell has accrued.
    step = Step(id="rev", label="Rev", instruction="rev", target=StepTarget("RPM", 2300, 2700),
                min_dwell_s=4.0, timeout_s=30.0)
    runner = ProtocolRunner(DiagnosticProtocol_single(step), max_adhoc=0)

    runner.offer(_sample("RPM", 1500), seq=1, t_ms=0)            # below band
    p = runner.progress(_sample("RPM", 1500), t_ms=0)
    assert p["pid"] == "RPM" and p["value"] == 1500
    assert p["target_low"] == 2300 and p["target_high"] == 2700
    assert p["in_range"] is False
    assert p["dwell_elapsed_s"] == 0.0 and p["dwell_required_s"] == 4.0

    runner.offer(_sample("RPM", 2500), seq=2, t_ms=1000)         # enters band → dwell starts
    runner.offer(_sample("RPM", 2500), seq=3, t_ms=3000)         # 2s held
    p = runner.progress(_sample("RPM", 2500), t_ms=3000)
    assert p["in_range"] is True
    assert p["dwell_elapsed_s"] == 2.0


def test_progress_is_none_for_instruction_only_step_and_when_complete():
    step = Step(id="warm", label="Warm", instruction="idle", target=None,
                min_dwell_s=0.0, timeout_s=5.0)
    runner = ProtocolRunner(DiagnosticProtocol_single(step), max_adhoc=0)
    assert runner.progress(_sample("RPM", 700), t_ms=0) is None   # no target → no gauge
    runner.skip()
    assert runner.is_complete()
    assert runner.progress(_sample("RPM", 700), t_ms=0) is None   # nothing active
