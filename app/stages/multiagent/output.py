"""MA8 멀티모달 출력: 글 답에 차트(분석 결과) · 근거 그림 · 음성을 붙인다.

차트는 데이터(labels · values)로만 돌려주고 그리는 것은 화면이 한다(Chart.js, 색은 --series-* 토큰) — 서버가 그림을 만들면 화면 테마
(다크 모드) · 접근성(표로 보기)을 맞출 수 없다. 음성은 TTS_URL(OpenAI 호환 /audio/speech)이 있을 때만, 근거 번호 [1] 은 읽지 않게 뺀다.
"""

import re
import secrets
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings


def audio_dir() -> Path:
    d = get_settings().data_dir / "tts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def speak(text: str) -> dict[str, Any] | None:
    st = get_settings()
    if not st.tts_url:
        return None
    spoken = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", text)[:2000]
    try:
        r = httpx.post(st.tts_url.rstrip("/") + "/audio/speech", json={"model": st.tts_model, "voice": st.tts_voice, "input": spoken, "response_format": "mp3"},
                       timeout=120)  # fmt: skip
        r.raise_for_status()
    except httpx.HTTPError as exc:
        return {"error": f"음성 합성 실패: {exc}"[:300]}
    name = f"{secrets.token_hex(8)}.mp3"
    (audio_dir() / name).write_bytes(r.content)
    return {"name": name, "url": f"/api/multiagent/audio/{name}", "bytes": len(r.content)}


def compose(text: str, analysis: dict[str, Any] | None, sources: list[dict[str, Any]], tts: bool) -> dict[str, Any]:
    images = [
        {"n": i + 1, "url": s["media"]["url"], "filename": s.get("filename")}
        for i, s in enumerate(sources)
        if isinstance(s.get("media"), dict)
    ]
    return {"text": text, "chart": (analysis or {}).get("chart"), "images": images[:4], "audio": speak(text) if tts else None,
            "tts_available": bool(get_settings().tts_url)}  # fmt: skip
