import re

from app.crud.chat_history_dao import ChatHistoryDao


def test_to_local_time_text_supports_multiple_timestamp_formats():
    dao = ChatHistoryDao()
    values = [
        "2026-03-23 10:00:00",
        1774231200,
        1774231200000,
        "2026-03-23T10:00:00+00:00",
        "2026-03-23T10:00:00Z",
    ]

    for value in values:
        output = dao._to_local_time_text(value)
        assert "T" in output
        assert re.search(r"[+-]\d{2}:\d{2}$", output) is not None


def test_to_local_time_text_fallback_for_invalid_value():
    dao = ChatHistoryDao()
    assert dao._to_local_time_text("not-a-timestamp") == "not-a-timestamp"

