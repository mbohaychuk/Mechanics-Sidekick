from types import SimpleNamespace

from app.agent.mcp_host import (
    is_destructive,
    mcp_tool_to_openai,
    sanitize_schema,
    select_openai_tools,
)


def _tool(name, *, schema=None, destructive=None, desc="d"):
    annotations = None if destructive is None else SimpleNamespace(destructiveHint=destructive)
    return SimpleNamespace(
        name=name,
        description=desc,
        inputSchema=schema if schema is not None else {"type": "object", "properties": {}},
        annotations=annotations,
    )


def test_sanitize_schema_normalizes_empty():
    assert sanitize_schema(None) == {"type": "object", "properties": {}}
    assert sanitize_schema({}) == {"type": "object", "properties": {}}


def test_sanitize_schema_passes_through_valid():
    schema = {"type": "object", "properties": {"pids": {"type": "array"}}, "required": ["pids"]}
    assert sanitize_schema(schema) == schema


def test_is_destructive_reads_annotation_defensively():
    assert is_destructive(_tool("clear_dtcs", destructive=True)) is True
    assert is_destructive(_tool("read_dtcs", destructive=False)) is False
    assert is_destructive(_tool("ping", destructive=None)) is False  # annotations is None


def test_mcp_tool_to_openai_shape():
    tool = _tool("read_dtcs", schema={"type": "object", "properties": {"scope": {"type": "string"}}})
    out = mcp_tool_to_openai(tool)
    assert out["type"] == "function"
    assert out["function"]["name"] == "read_dtcs"
    assert out["function"]["description"] == "d"
    assert out["function"]["parameters"]["properties"] == {"scope": {"type": "string"}}


def test_select_openai_tools_filters_destructive_and_denylist():
    tools = [
        _tool("read_dtcs", destructive=False),
        _tool("clear_dtcs", destructive=True),
        _tool("ping", destructive=None),
    ]
    selected = select_openai_tools(tools, denylist={"ping"})
    names = [t["function"]["name"] for t in selected]
    assert names == ["read_dtcs"]
