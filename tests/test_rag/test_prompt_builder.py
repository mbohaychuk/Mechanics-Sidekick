from unittest.mock import MagicMock
from app.rag.prompt_builder import build_system_prompt, build_messages


def _make_job(title="Front Brake Replacement"):
    job = MagicMock()
    job.title = title
    return job


def _make_vehicle(year=2018, make="Ford", model="F-150", engine="5.0L V8"):
    v = MagicMock()
    v.year = year
    v.make = make
    v.model = model
    v.engine = engine
    return v


def _make_chunk(content, doc_id=1, page_number=5, context_summary=None, section_title=None):
    c = MagicMock()
    c.content = content
    c.document_id = doc_id
    c.page_number = page_number
    c.context_summary = context_summary
    c.section_title = section_title
    return c


def test_system_prompt_enforces_grounding():
    prompt = build_system_prompt(_make_vehicle())
    assert "answer only using" in prompt.lower()
    assert "never invent" in prompt.lower()
    assert "could not find" in prompt.lower()
    assert "cite" in prompt.lower() or "source" in prompt.lower()


def test_system_prompt_includes_vehicle_engine():
    prompt = build_system_prompt(_make_vehicle(engine="4.2L V8"))
    assert "4.2L V8" in prompt


def test_build_messages_last_message_is_user_question():
    messages = build_messages(
        _make_job(), _make_vehicle(), [],
        [(_make_chunk("Torque 129 Nm"), 0.9)],
        "What is the torque?",
        {1: "brake_manual.pdf"},
    )
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "What is the torque?"


def test_build_messages_includes_chunk_content_and_filename():
    chunk = _make_chunk("Torque spec is 129 Nm", doc_id=1, page_number=214)
    messages = build_messages(
        _make_job(), _make_vehicle(), [],
        [(chunk, 0.95)],
        "Torque spec?",
        {1: "brake_manual.pdf"},
    )
    full_text = " ".join(m["content"] for m in messages)
    assert "129 Nm" in full_text
    assert "brake_manual.pdf" in full_text
    assert "214" in full_text


def test_build_messages_includes_recent_history():
    prior_msg = MagicMock()
    prior_msg.role = "user"
    prior_msg.content = "Previous question"

    messages = build_messages(
        _make_job(), _make_vehicle(), [prior_msg],
        [(_make_chunk("Some content"), 0.8)],
        "New question",
        {1: "doc.pdf"},
    )
    contents = [m["content"] for m in messages]
    assert "Previous question" in contents


def test_build_messages_includes_context_summary_when_present():
    chunk = _make_chunk(
        "Tighten bolts to 23 Nm",
        context_summary="This chunk covers 4.2L V8 cylinder head torque specs.",
    )
    messages = build_messages(
        _make_job(), _make_vehicle(), [],
        [(chunk, 0.9)],
        "Torque?",
        {1: "manual.pdf"},
    )
    full_text = " ".join(m["content"] for m in messages)
    assert "4.2L V8 cylinder head torque specs" in full_text


def test_build_messages_includes_section_title_when_present():
    chunk = _make_chunk("Tighten bolts to 23 Nm", section_title="CYLINDER HEAD TORQUE SPECS")
    messages = build_messages(
        _make_job(), _make_vehicle(), [],
        [(chunk, 0.9)],
        "Torque?",
        {1: "manual.pdf"},
    )
    full_text = " ".join(m["content"] for m in messages)
    assert "CYLINDER HEAD TORQUE SPECS" in full_text


def test_build_messages_omits_summary_line_when_none():
    chunk = _make_chunk("Tighten bolts to 23 Nm", context_summary=None)
    messages = build_messages(
        _make_job(), _make_vehicle(), [],
        [(chunk, 0.9)],
        "Torque?",
        {1: "manual.pdf"},
    )
    full_text = " ".join(m["content"] for m in messages)
    assert "Summary:" not in full_text


def test_build_messages_has_multiple_system_messages():
    messages = build_messages(
        _make_job(), _make_vehicle(), [],
        [(_make_chunk("Content"), 0.9)],
        "Question?",
        {1: "manual.pdf"},
    )
    system_count = sum(1 for m in messages if m["role"] == "system")
    assert system_count >= 3  # system prompt + job context + manual excerpts
