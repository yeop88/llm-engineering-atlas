"""LLM 호출: OpenAI 호환 Chat Completions API 와 Claude Messages API (httpx 로 직접 호출, SDK 의존성 없음).

평가 질문 생성처럼 '프롬프트 → 텍스트/JSON' 만 필요하므로 공통 인터페이스는 chat() / chat_json() 하나다.
"""

import json
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings

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
        raise LLMError(
            "LLM 이 설정되지 않았습니다. .env 에 OPENAI_API_KEY·OPENAI_MODEL 또는 ANTHROPIC_API_KEY 를 넣으세요 (docs/guides/llm.md)."
        )
    if p == "openai":
        m = model or s.openai_model
        if not m:
            raise LLMError("OPENAI_MODEL 을 설정하거나 요청에 모델 이름을 넣으세요.")
        # 로컬 서버(Ollama·vLLM 등)는 키가 없어도 된다. 모델별 주소가 있으면 그 서버로 보낸다(OPENAI_MODEL_URLS).
        url = (s.openai_model_urls or {}).get(m) or s.openai_base_url
        return LLMConfig("openai", m, url.rstrip("/"), s.openai_api_key, s.llm_timeout)
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


def _request(
    cfg: LLMConfig,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float | None,
    json_mode: bool = False,
    stream: bool = False,
    no_cache: bool = False,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """제공자별 (URL, 헤더, 본문)."""
    if cfg.provider == "openai":
        body: dict[str, Any] = {"model": cfg.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        # 공식 API 의 최신 모델은 max_completion_tokens, 호환 서버는 대부분 max_tokens 를 받는다
        body["max_completion_tokens" if "api.openai.com" in cfg.base_url else "max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if get_settings().llm_disable_thinking and "api.openai.com" not in cfg.base_url:
            body["chat_template_kwargs"] = {"enable_thinking": False}  # llama.cpp·vLLM 이 템플릿에 전달
        if no_cache and "api.openai.com" not in cfg.base_url:
            # llama-server 는 앞서 처리한 프롬프트를 재사용한다(cache_prompt). 속도를 비교할 때 한 모델만 이전 실행의 캐시를 쓰면
            # 읽기 시간이 거의 0 이 되어 비교가 무너진다 — 실측에서 Q4 만 6초로 나온 원인. 공식 API 는 모르는 인자를 거부해 보내지 않는다.
            body["cache_prompt"] = False
        if stream:
            body |= {"stream": True, "stream_options": {"include_usage": True}}
        headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
        return f"{cfg.base_url}/chat/completions", headers, body
    body = {"model": cfg.model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}]}
    if temperature is not None:
        body["temperature"] = temperature
    if stream:
        body["stream"] = True
    return cfg.base_url, {"x-api-key": cfg.api_key or "", "anthropic-version": ANTHROPIC_VERSION}, body


def chat(
    cfg: LLMConfig,
    system: str,
    user: str,
    max_tokens: int = 2048,
    temperature: float | None = 0.3,
    json_mode: bool = False,
    no_cache: bool = False,
) -> dict[str, Any]:
    """→ {"text", "usage": {"input_tokens", "output_tokens"}, "seconds"}"""
    started = time.perf_counter()
    url, headers, body = _request(cfg, system, user, max_tokens, temperature, json_mode, no_cache=no_cache)
    if cfg.provider == "openai":
        data = _post(cfg, url, headers, body)
        try:
            msg = data["choices"][0]["message"]
            text = msg.get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"응답 형식을 해석할 수 없습니다: {str(data)[:200]}") from exc
        u = data.get("usage") or {}
        usage = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")}
        if tm := data.get("timings"):
            # llama-server 가 주는 단계별 시간. 근거를 길게 넣는 RAG 는 '읽기'(프롬프트 처리)가 '쓰기'(생성)보다 오래 걸릴 수 있어
            # 둘을 나눠 봐야 양자화 · 하드웨어의 속도 차이를 바르게 읽는다.
            usage |= {"prompt_tokens_evaluated": tm.get("prompt_n"), "prompt_ms": tm.get("prompt_ms"), "prompt_per_second": tm.get("prompt_per_second"),
                      "generation_ms": tm.get("predicted_ms"), "generation_per_second": tm.get("predicted_per_second")}  # fmt: skip
        if not text.strip() and msg.get("reasoning_content"):
            usage["reasoning_only"] = True  # 생각만 하다 토큰 한도에 걸림
        if data["choices"][0].get("finish_reason") == "length":
            usage["truncated"] = True
    else:
        data = _post(cfg, url, headers, body)
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        u = data.get("usage") or {}
        usage = {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens")}
        if data.get("stop_reason") == "max_tokens":
            usage["truncated"] = True
    seconds = time.perf_counter() - started
    text = _THINK.sub("", text).strip()
    out_tok = usage.get("output_tokens")
    return {
        "text": text,
        "usage": usage,
        "seconds": round(seconds, 2),
        "tokens_per_second": round(out_tok / seconds, 1) if out_tok and seconds else None,
    }


_THINK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class _ThinkFilter:
    """스트림 조각에서 <think>…</think> 구간을 걸러낸다 (태그가 조각 경계에서 잘려도 동작)."""

    def __init__(self) -> None:
        self.buf = ""
        self.inside = False

    def feed(self, piece: str) -> str:
        self.buf += piece
        out = ""
        while self.buf:
            tag = "</think>" if self.inside else "<think>"
            i = self.buf.find(tag)
            if i >= 0:
                if not self.inside:
                    out += self.buf[:i]
                self.buf = self.buf[i + len(tag) :].lstrip() if self.inside else self.buf[i + len(tag) :]
                self.inside = not self.inside
                continue
            keep = next((k for k in range(len(tag) - 1, 0, -1) if self.buf.endswith(tag[:k])), 0)  # 태그 앞부분일 수 있는 끝
            if not self.inside:
                out += self.buf[: len(self.buf) - keep]
            self.buf = self.buf[len(self.buf) - keep :] if keep else ""
            break
        return out

    def flush(self) -> str:
        rest, self.buf = ("" if self.inside else self.buf), ""
        return rest


def chat_stream(
    cfg: LLMConfig, system: str, user: str, max_tokens: int = 2048, temperature: float | None = 0.3
) -> Iterator[dict[str, Any]]:
    """{"delta": 글자 조각} 을 차례로, 마지막에 {"done": True, "text", "usage", "seconds", "tokens_per_second"} 를 낸다."""
    started = time.perf_counter()
    url, headers, body = _request(cfg, system, user, max_tokens, temperature, stream=True)
    usage: dict[str, Any] = {}
    parts: list[str] = []
    flt = _ThinkFilter()
    first: float | None = None  # 첫 글자가 나온 시각 (그 전까지는 근거 읽기 = 프롬프트 처리)
    try:
        with httpx.Client(timeout=cfg.timeout, transport=_transport) as client, client.stream("POST", url, headers=headers, json=body) as r:
            if r.status_code >= 400:
                r.read()
                raise LLMError(f"{PROVIDERS[cfg.provider]} 호출 실패 ({cfg.model}) — HTTP {r.status_code}: {r.text[:300]}")
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    ev = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                piece = ""
                if cfg.provider == "openai":
                    for ch in ev.get("choices") or []:
                        piece += (ch.get("delta") or {}).get("content") or ""
                        if ch.get("finish_reason") == "length":
                            usage["truncated"] = True
                    if ev.get("usage"):
                        usage |= {"input_tokens": ev["usage"].get("prompt_tokens"), "output_tokens": ev["usage"].get("completion_tokens")}
                else:
                    t = ev.get("type")
                    if t == "content_block_delta":
                        piece = (ev.get("delta") or {}).get("text") or ""
                    elif t == "message_start":
                        usage["input_tokens"] = ((ev.get("message") or {}).get("usage") or {}).get("input_tokens")
                    elif t == "message_delta":
                        usage["output_tokens"] = (ev.get("usage") or {}).get("output_tokens")
                        if (ev.get("delta") or {}).get("stop_reason") == "max_tokens":
                            usage["truncated"] = True
                    elif t == "error":
                        raise LLMError(f"{PROVIDERS[cfg.provider]} 스트림 오류: {ev.get('error')}")
                text = flt.feed(piece) if piece else ""
                if text:
                    if first is None:
                        first = time.perf_counter()
                    parts.append(text)
                    yield {"delta": text}
    except httpx.HTTPError as exc:
        raise LLMError(f"{PROVIDERS[cfg.provider]} 연결 실패 ({cfg.model}) — {type(exc).__name__}: {exc}") from exc
    tail = flt.flush()
    if tail:
        parts.append(tail)
        yield {"delta": tail}
    end = time.perf_counter()
    out_tok = usage.get("output_tokens")
    gen = end - first if first else 0.0
    yield {
        "done": True,
        "text": "".join(parts).strip(),
        "usage": usage,
        "seconds": round(end - started, 2),
        "ttft_s": round(first - started, 2) if first else None,  # 첫 글자까지 (긴 근거일수록 길다)
        "tokens_per_second": round(out_tok / gen, 1) if out_tok and gen > 0 else None,  # 생성 속도
    }


def list_models(cfg: LLMConfig) -> list[str]:
    """OpenAI 호환 서버에 올라와 있는 모델 이름 (/models)."""
    if cfg.provider != "openai":
        return [cfg.model]
    headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
    try:
        with httpx.Client(timeout=10, transport=_transport) as client:
            r = client.get(f"{cfg.base_url}/models", headers=headers)
            r.raise_for_status()
            return [m["id"] for m in r.json().get("data", [])]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise LLMError(f"모델 목록을 가져오지 못했습니다 ({cfg.base_url}): {exc}") from exc


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
