"""LLM 클라이언트: 제공자별 요청 형식·응답 해석·재시도·JSON 추출 (가짜 HTTP 응답)."""

import json

import httpx
import pytest

from app.config import get_settings
from app.services import llm


@pytest.fixture
def fake(monkeypatch):
    calls = []
    replies = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        status, body = replies.pop(0) if replies else (200, {})
        return httpx.Response(status, json=body)

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    return calls, replies


def _settings(monkeypatch, **kw):
    s = get_settings()
    for k in ("llm_provider", "openai_api_key", "openai_model", "anthropic_api_key"):
        monkeypatch.setattr(s, k, None)
    for k, v in kw.items():
        monkeypatch.setattr(s, k, v)
    return s


def test_resolve_picks_configured_provider(monkeypatch):
    _settings(monkeypatch)
    with pytest.raises(llm.LLMError):
        llm.resolve()
    _settings(monkeypatch, openai_model="qwen3:8b", openai_base_url="http://localhost:11434/v1/")
    cfg = llm.resolve()
    assert (cfg.provider, cfg.model, cfg.base_url, cfg.api_key) == (
        "openai",
        "qwen3:8b",
        "http://localhost:11434/v1",
        None,
    )  # 로컬은 키 없이
    _settings(monkeypatch, anthropic_api_key="sk-x")
    assert llm.resolve().provider == "anthropic"
    assert llm.resolve(model="other").model == "other"
    with pytest.raises(llm.LLMError):
        llm.resolve("openai")  # 모델 이름이 없음
    assert "sk-x" not in json.dumps(llm.status())  # 키는 노출하지 않음


def test_openai_compatible_request_and_parse(monkeypatch, fake):
    calls, replies = fake
    _settings(monkeypatch, openai_model="m1", openai_api_key="k", openai_base_url="http://local/v1")
    replies.append(
        (200, {"choices": [{"message": {"content": '```json\n{"a": 1}\n```'}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
    )
    obj, res = llm.chat_json(llm.resolve(), "sys", "hi", max_tokens=50)
    req = json.loads(calls[0].content)
    assert str(calls[0].url) == "http://local/v1/chat/completions" and calls[0].headers["authorization"] == "Bearer k"
    assert req["max_tokens"] == 50 and req["response_format"] == {"type": "json_object"} and req["messages"][0]["role"] == "system"
    assert obj == {"a": 1} and res["usage"] == {"input_tokens": 5, "output_tokens": 3}


def test_anthropic_request_retry_and_errors(monkeypatch, fake):
    calls, replies = fake
    _settings(monkeypatch, anthropic_api_key="sk-a")
    replies += [
        (529, {"error": "overloaded"}),
        (200, {"content": [{"type": "text", "text": "안녕"}], "usage": {"input_tokens": 7, "output_tokens": 2}, "stop_reason": "end_turn"}),
    ]
    res = llm.chat(llm.resolve(), "sys", "hi", max_tokens=10)
    assert res["text"] == "안녕" and len(calls) == 2  # 과부하는 재시도
    req = json.loads(calls[1].content)
    assert calls[1].headers["x-api-key"] == "sk-a" and calls[1].headers["anthropic-version"] == llm.ANTHROPIC_VERSION
    assert req["system"] == "sys" and req["messages"] == [{"role": "user", "content": "hi"}] and req["max_tokens"] == 10
    replies.append((401, {"error": "bad key"}))
    with pytest.raises(llm.LLMError, match="401"):
        llm.chat(llm.resolve(), "s", "u")
    assert len(calls) == 3  # 인증 오류는 재시도하지 않음


def test_parse_json_variants():
    assert llm.parse_json('설명입니다.\n[{"q": "x"}] 끝') == [{"q": "x"}]
    assert llm.parse_json('{"questions": []}') == {"questions": []}
    with pytest.raises(llm.LLMError):
        llm.parse_json("JSON 없음")


def test_llm_api_endpoints(client, monkeypatch, fake):
    _, replies = fake
    _settings(monkeypatch)
    assert "error" in client.get("/api/llm/status").json()["default"]
    assert client.post("/api/llm/test", json={}).status_code == 400
    _settings(monkeypatch, openai_model="m", openai_base_url="http://local/v1")
    replies.append((200, {"choices": [{"message": {"content": "벡터입니다"}}]}))
    r = client.post("/api/llm/test", json={"prompt": "hi"}).json()
    assert r["text"] == "벡터입니다" and r["config"]["model"] == "m"
