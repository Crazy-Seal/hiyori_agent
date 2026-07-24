import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from app.agent.models.llm_client import LLMClient, LLMConfig


SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}


def _completion(content: str | None, finish_reason: str | None = "stop"):
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def _client_with_responses(responses):
    client = LLMClient(
        LLMConfig(model="structured-model", api_key="test-key", base_url="http://x/v1")
    )
    pending = list(responses)
    calls: list[dict] = []

    async def fake_create(**kwargs):
        calls.append(kwargs)
        return pending.pop(0)

    client._client.chat.completions.create = fake_create
    return client, calls


def _invoke(client: LLMClient):
    async def scenario():
        try:
            return await client.ainvoke_structured(
                [{"role": "user", "content": "extract"}],
                SCHEMA,
            )
        finally:
            await client.close()

    return asyncio.run(scenario())


def test_ainvoke_structured_returns_valid_json_without_retry() -> None:
    client, calls = _client_with_responses([
        _completion('{"value":"ok"}'),
    ])

    assert _invoke(client) == {"value": "ok"}
    assert len(calls) == 1


@pytest.mark.parametrize(
    "finish_reason",
    ["length", "content_filter", "tool_calls", None],
)
def test_ainvoke_structured_retries_any_non_stop_finish_reason(
    finish_reason,
    caplog,
) -> None:
    client, calls = _client_with_responses([
        _completion('{"value":"incomplete"}', finish_reason),
        _completion('{"value":"ok"}'),
    ])

    with caplog.at_level(logging.INFO, logger="app.agent.models.llm_client"):
        result = _invoke(client)

    expected_reason = finish_reason or "unknown"
    assert result == {"value": "ok"}
    assert len(calls) == 2
    assert f"finish_reason={expected_reason}" in caplog.text
    assert "attempt=1/2" in caplog.text
    assert "结构化输出重试成功" in caplog.text


def test_ainvoke_structured_retries_json_decode_error_without_logging_content(
    caplog,
) -> None:
    secret_marker = "PRIVATE_MEMORY_CONTENT"
    client, calls = _client_with_responses([
        _completion(f'{{"value":"{secret_marker}'),
        _completion('{"value":"ok"}'),
    ])

    with caplog.at_level(logging.INFO, logger="app.agent.models.llm_client"):
        result = _invoke(client)

    assert result == {"value": "ok"}
    assert len(calls) == 2
    assert "JSONDecodeError" in caplog.text
    assert "line=1" in caplog.text
    assert "column=" in caplog.text
    assert "position=" in caplog.text
    assert secret_marker not in caplog.text


def test_ainvoke_structured_retries_empty_content() -> None:
    client, calls = _client_with_responses([
        _completion(None),
        _completion('{"value":"ok"}'),
    ])

    assert _invoke(client) == {"value": "ok"}
    assert len(calls) == 2


def test_ainvoke_structured_raises_after_two_non_stop_responses() -> None:
    client, calls = _client_with_responses([
        _completion('{"value":"first"}', "length"),
        _completion('{"value":"second"}', "content_filter"),
    ])

    with pytest.raises(
        RuntimeError,
        match=r"finish_reason=content_filter.*attempts=2",
    ):
        _invoke(client)

    assert len(calls) == 2


def test_ainvoke_structured_reraises_last_json_decode_error() -> None:
    client, calls = _client_with_responses([
        _completion('{"value":"first'),
        _completion('{"value":"second'),
    ])

    with pytest.raises(json.JSONDecodeError) as exc_info:
        _invoke(client)

    assert exc_info.value.doc == '{"value":"second'
    assert len(calls) == 2
