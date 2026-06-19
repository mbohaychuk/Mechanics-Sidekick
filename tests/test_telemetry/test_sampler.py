import asyncio

from app.telemetry.sampler import TelemetrySampler


def test_sampler_reads_union_persists_and_fans_out():
    persisted: list[dict] = []

    async def call_live(pids):
        # echo a value per requested pid
        return {p: {"value": len(p), "unit": "x"} for p in pids}

    async def scenario():
        sampler = TelemetrySampler(
            call_live=call_live, persist=persisted.append, target_hz=50.0, min_interval_s=0.0
        )
        a = sampler.subscribe(["RPM"], queue_size=4)
        b = sampler.subscribe(["RPM", "SPEED"], queue_size=4)
        assert sampler.union_pids == ["RPM", "SPEED"]
        sampler.start()
        # collect one sample on each subscriber
        ev_a = await asyncio.wait_for(a.queue.get(), timeout=1.0)
        ev_b = await asyncio.wait_for(b.queue.get(), timeout=1.0)
        await sampler.stop()
        return ev_a, ev_b, sampler.achieved_hz

    ev_a, ev_b, achieved_hz = asyncio.run(scenario())
    assert ev_a["type"] == "sample"
    assert set(ev_a["values"]) == {"RPM"}            # filtered to A's PIDs
    assert set(ev_b["values"]) == {"RPM", "SPEED"}   # filtered to B's PIDs
    assert persisted and set(persisted[0]["values"]) == {"RPM", "SPEED"}  # union persisted
    assert set(persisted[0]) == {"seq", "t_offset_ms", "values"}          # persisted sample shape
    assert achieved_hz > 0                                                 # effective rate is positive


def test_subscriber_offer_is_latest_wins():
    from app.telemetry.sampler import Subscriber

    sub = Subscriber(["RPM"], queue_size=1)
    sub.offer({"seq": 1})
    sub.offer({"seq": 2})  # drops seq 1, keeps newest
    assert sub.queue.qsize() == 1
    assert sub.queue.get_nowait()["seq"] == 2


def test_sampler_reports_error_on_read_failure():
    from app.telemetry.parse import LiveReadError

    async def call_live(pids):
        raise LiveReadError("[tool error] boom")

    async def scenario():
        sampler = TelemetrySampler(call_live=call_live, persist=lambda s: None, target_hz=50.0, min_interval_s=0.0)
        sub = sampler.subscribe(["RPM"], queue_size=4)
        sampler.start()
        ev = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
        await sampler.stop()
        return ev, sampler.error

    ev, err = asyncio.run(scenario())
    assert ev["type"] == "disconnected"
    assert err is not None
