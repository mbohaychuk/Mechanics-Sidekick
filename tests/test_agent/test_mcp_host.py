import sys
from pathlib import Path

import pytest

from app.agent.mcp_host import ObdMcpHost

STUB = str(Path(__file__).resolve().parents[1] / "fixtures" / "stub_mcp_server.py")


def test_start_fails_for_missing_command_and_degrades():
    host = ObdMcpHost(command="/nonexistent-binary-xyz", args=[], start_timeout=5.0)
    try:
        assert host.start() is False
        assert host.available is False
        assert host.openai_tools() == []
        assert host.handles("read_dtcs") is False
        assert host.call("read_dtcs", {}).startswith("[obd unavailable]")
    finally:
        host.stop()


def test_connects_lists_filtered_tools_and_calls():
    host = ObdMcpHost(command=sys.executable, args=[STUB], start_timeout=20.0)
    assert host.start() is True
    try:
        names = [t["function"]["name"] for t in host.openai_tools()]
        assert "echo" in names          # read-only tool advertised
        assert "wipe" not in names       # destructive tool filtered out
        assert host.handles("echo") is True
        assert host.handles("wipe") is False
        assert "echo:hi" in host.call("echo", {"text": "hi"})
        # The host refuses a name it did not advertise, without calling the server.
        assert host.call("wipe", {}).startswith("[obd error]")
    finally:
        host.stop()


def test_denylist_drops_named_tool():
    host = ObdMcpHost(command=sys.executable, args=[STUB], denylist={"echo"}, start_timeout=20.0)
    assert host.start() is True
    try:
        assert host.openai_tools() == []  # echo denylisted, wipe destructive
    finally:
        host.stop()
