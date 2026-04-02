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


def _make_chunk(content, doc_id=1, page_number=5):
    c = MagicMock()
    c.content = content
    c.document_id = doc_id
    c.page_number = page_number
    return c


def test_system_prompt_enforces_grounding():
    prompt = build_system_prompt()
    assert "answer only using" in prompt.lower()
    assert "never invent" in prompt.lower()
    assert "could not find" in prompt.lower()
    assert "cite" in prompt.lower() or "source" in prompt.lower()


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


def test_build_messages_has_multiple_system_messages():
    messages = build_messages(
        _make_job(), _make_vehicle(), [],
        [(_make_chunk("Content"), 0.9)],
        "Question?",
        {1: "manual.pdf"},
    )
    system_count = sum(1 for m in messages if m["role"] == "system")
    assert system_count >= 3  # system prompt + job context + manual excerpts
