"""LLM 호출: OpenAI 호환 Chat Completions API 와 Claude Messages API (httpx 로 직접 호출, SDK 의존성 없음).

평가 질문 생성처럼 '프롬프트 → 텍스트/JSON' 만 필요하므로 공통 인터페이스는 chat() / chat_json() 하나다.
"""

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

PROVIDERS = {"openai": "OpenAI 호환 API", "anthropic": "Claude API"}
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}

_transport: httpx.BaseTransport | None = None  # 테스트에서 가짜 응답을 넣을 때 사용


class LLMError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    provider: str
    model: str
    base_url: str = ""
    api_key: str | None = None
    timeout: float = 120.0

    def public(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "base_url": self.base_url if self.provider == "openai" else ""}


def resolve(provider: str | None = None, model: str | None = None) -> LLMConfig:
    """요청에서 고른 제공자/모델 → 설정(.env) 순으로 정한다."""
    s = get_settings()
    p = provider or s.llm_provider or ("openai" if s.openai_api_key or s.openai_model else "anthropic" if s.anthropic_api_key else None)
    if p not in PROVIDERS:
        raise LLMError("LLM 이 설정되지 않았습니다. .env 에 OPENAI_API_KEY·OPENAI_MODEL 또는 ANTHROPIC_API_KEY 를 넣으세요 (docs/llm.md).")
    if p == "openai":
        m = model or s.openai_model
        if not m:
            raise LLMError("OPENAI_MODEL 을 설정하거나 요청에 모델 이름을 넣으세요.")
        # 로컬 서버(Ollama·vLLM 등)는 키가 없어도 된다
        return LLMConfig("openai", m, s.openai_base_url.rstrip("/"), s.openai_api_key, s.llm_timeout)
    if not s.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")
    return LLMConfig("anthropic", model or s.anthropic_model, ANTHROPIC_URL, s.anthropic_api_key, s.llm_timeout)


def status() -> dict[str, Any]:
    """설정 상태 (키 값은 노출하지 않는다)."""
    s = get_settings()
    try:
        default = resolve().public()
    except LLMError as exc:
        default = {"error": str(exc)}
    return {
        "default": default,
        "providers": {
            "openai": {
                "configured": bool(s.openai_model),
                "base_url": s.openai_base_url,
                "model": s.openai_model,
                "has_key": bool(s.openai_api_key),
            },
            "anthropic": {"configured": bool(s.anthropic_api_key), "model": s.anthropic_model},
        },
    }


def _post(cfg: LLMConfig, url: str, headers: dict[str, str], body: dict[str, Any], retries: int = 3) -> dict[str, Any]:
    last = ""
    with httpx.Client(timeout=cfg.timeout, transport=_transport) as client:
        for attempt in range(retries + 1):
            try:
                r = client.post(url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                if r.status_code < 400:
                    return r.json()
                last = f"HTTP {r.status_code}: {r.text[:300]}"
                if r.status_code not in RETRY_STATUS:
                    break
            if attempt < retries:
                time.sleep(min(20.0, 1.5 * 2**attempt))
    raise LLMError(f"{PROVIDERS[cfg.provider]} 호출 실패 ({cfg.model}) — {last}")


def chat(
    cfg: LLMConfig, system: str, user: str, max_tokens: int = 2048, temperature: float | None = 0.3, json_mode: bool = False
) -> dict[str, Any]:
    """→ {"text", "usage": {"input_tokens", "output_tokens"}, "seconds"}"""
    started = time.perf_counter()
    if cfg.provider == "openai":
        body: dict[str, Any] = {"model": cfg.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        # 공식 API 의 최신 모델은 max_completion_tokens, 호환 서버는 대부분 max_tokens 를 받는다
        body["max_completion_tokens" if "api.openai.com" in cfg.base_url else "max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
        data = _post(cfg, f"{cfg.base_url}/chat/completions", headers, body)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"응답 형식을 해석할 수 없습니다: {str(data)[:200]}") from exc
        u = data.get("usage") or {}
        usage = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")}
    else:
        body = {"model": cfg.model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}]}
        if temperature is not None:
            body["temperature"] = temperature
        headers = {"x-api-key": cfg.api_key or "", "anthropic-version": ANTHROPIC_VERSION}
        data = _post(cfg, cfg.base_url, headers, body)
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        u = data.get("usage") or {}
        usage = {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens")}
        if data.get("stop_reason") == "max_tokens":
            usage["truncated"] = True
    return {"text": text, "usage": usage, "seconds": round(time.perf_counter() - started, 2)}


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str) -> Any:
    """코드 블록·앞뒤 설명이 섞여 있어도 첫 JSON 객체/배열을 꺼낸다."""
    t = _FENCE.sub("", text.strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if starts:
        try:
            obj, _ = json.JSONDecoder().raw_decode(t[min(starts) :])
            return obj
        except json.JSONDecodeError:
            pass
    raise LLMError(f"LLM 응답에서 JSON 을 찾지 못했습니다: {text[:200]}")


def chat_json(cfg: LLMConfig, system: str, user: str, **kw: Any) -> tuple[Any, dict[str, Any]]:
    res = chat(cfg, system, user, json_mode=cfg.provider == "openai", **kw)
    return parse_json(res["text"]), res
