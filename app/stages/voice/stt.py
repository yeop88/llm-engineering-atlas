"""VC1 스트리밍 음성 인식: 끝점마다 발화 조각을 인식 · 용어 사전(제품 모델 · 오류 코드)으로 편향 · 코드 표기 복원 · 정확도 평가.

엔진은 둘: openai — OpenAI 호환 /audio/transcriptions(STT_URL: whisper.cpp server · 클라우드), local — transformers Whisper(VOICE_STT_LOCAL_MODEL,
처음 쓸 때 내려받음). 스트리밍은 '말하는 도중 조각마다'로 한다 — 턴 관리(VC2)가 끝점 후보를 낼 때마다 그 조각만 인식해, 통화가 끝나기
전에 처리를 시작한다.

용어 사전은 두 겹: (1) 인식기에 미리 주는 말(prompt — Whisper 는 앞 문맥에 나온 낱말을 더 잘 받아 적음), (2) 받아 적은 글의 코드 읽기를 표기로
복원 — 고객은 'E4' 를 '이 사' · '이사', 'WM-200' 을 '더블유엠 이백' 으로 말하고 인식기는 소리대로 적는다. 복원은 컬렉션에 실제로 있는
모델 · 코드로 바꿀 때만(사전에 없는 '이사'를 'E4' 로 바꾸면 '이사 가요'가 망가짐).
"""

import re
import time
from functools import lru_cache
from typing import Any

import httpx
import numpy as np

from app.core.config import get_settings
from app.stages.voice import audio

LETTERS = {"에이": "A", "비": "B", "씨": "C", "디": "D", "이": "E", "에프": "F", "지": "G", "에이치": "H", "아이": "I", "제이": "J", "케이": "K",
           "엘": "L", "엠": "M", "엔": "N", "오": "O", "피": "P", "큐": "Q", "알": "R", "에스": "S", "티": "T", "유": "U", "브이": "V",
           "더블유": "W", "엑스": "X", "와이": "Y", "제트": "Z", "지드": "Z"}  # fmt: skip
DIGITS = {
    "공": "0",
    "영": "0",
    "일": "1",
    "이": "2",
    "삼": "3",
    "사": "4",
    "오": "5",
    "육": "6",
    "륙": "6",
    "칠": "7",
    "팔": "8",
    "구": "9",
}
UNITS = {"십": 10, "백": 100, "천": 1000}


def sino_number(s: str) -> int | None:
    """'이백' → 200, '삼십오' → 35, '이공공' → 200(숫자를 하나씩 읽은 경우)."""
    if s and all(ch in DIGITS for ch in s) and len(s) > 1 and not any(ch in UNITS for ch in s):
        return int("".join(DIGITS[ch] for ch in s))
    total, cur = 0, 0
    for ch in s:
        if ch in DIGITS:
            cur = int(DIGITS[ch])
        elif ch in UNITS:
            total += (cur or 1) * UNITS[ch]
            cur = 0
        else:
            return None
    return total + cur if s else None


def _spellings(term: str) -> list[str]:
    """표기 → 사람이 읽는 소리 몇 가지. 'E4' → ['이사', '이 사'], 'WM-200' → ['더블유엠이백', '더블유엠 이백', ...]."""
    rev_l = {}
    for k, v in LETTERS.items():
        rev_l.setdefault(v, k)
    rev_d = {"0": "공", "1": "일", "2": "이", "3": "삼", "4": "사", "5": "오", "6": "육", "7": "칠", "8": "팔", "9": "구"}
    m = re.fullmatch(r"([A-Za-z]+)-?(\d*)", term)
    if not m:
        return []
    letters = "".join(rev_l.get(c.upper(), c) for c in m.group(1))
    num = m.group(2)
    if not num:
        return [letters]
    digitwise = "".join(rev_d[d] for d in num)
    out = [letters + digitwise, f"{letters} {digitwise}", letters + " " + " ".join(rev_d[d] for d in num)]
    if len(num) >= 2 and num[0] != "0":  # 자릿값으로 읽기(이백 · 삼십오)
        word = _sino_word(int(num))
        out += [letters + word, f"{letters} {word}"]
    return list(dict.fromkeys(out))


def _sino_word(n: int) -> str:
    rev = {1: "일", 2: "이", 3: "삼", 4: "사", 5: "오", 6: "육", 7: "칠", 8: "팔", 9: "구"}
    out = ""
    for unit, name in ((1000, "천"), (100, "백"), (10, "십")):
        q, n = divmod(n, unit)
        if q:
            out += ("" if q == 1 else rev[q]) + name
    return out + (rev[n] if n else "")


def restore_terms(text: str, vocab: list[str]) -> tuple[str, list[dict[str, str]]]:
    """받아 적은 소리 → 사전의 표기. 긴 소리부터 바꿔 'E4' 의 '이사' 가 'WM-200' 의 일부를 먼저 먹지 않게."""
    pairs = sorted(((sp, t) for t in vocab for sp in _spellings(t)), key=lambda x: -len(x[0]))
    fixes = []
    # 짧은 오류 코드(E4 · OE)는 소리가 흔한 낱말과 같다('이사' · '오이') — 코드를 말하는 문맥(오류 · 에러 · 코드 · 떠요 · 표시)일 때만 바꾼다
    code_ctx = bool(re.search(r"오류|에러|코드|떠|뜨|표시|깜빡|나와|나오", text))
    for sp, t in pairs:
        if re.fullmatch(r"[A-Za-z]{1,2}\d?", t) and not code_ctx:
            continue
        # 앞뒤가 한글이면 낱말 안이라 바꾸지 않는다('이사' 는 '이사하다' 에서 바꾸면 안 됨) — 조사(가 · 는 · 에서)는 뒤에 붙어도 됨.
        # '이다' 활용(인데 · 입니다)과 랑 · 만 도 붙는다 — 빠져 있어 고객이 가장 자주 하는 'WM-200인데요' · 'WM-200입니다' 가 복원되지 않았다
        pat = re.compile(rf"(?<![가-힣A-Za-z0-9]){re.escape(sp)}(?=$|[^가-힣A-Za-z0-9]|[이가은는을를에의도로와과인입랑만])")
        if pat.search(text):
            text = pat.sub(t, text)
            fixes.append({"from": sp, "to": t})
    return text, fixes


def vocab_prompt(vocab: list[str], limit: int = 40) -> str:
    """인식기 앞 문맥: 'AS 상담 통화. 용어: WM-200, E4, …' — Whisper 는 이 문맥의 낱말 표기를 따라 적는 경향이 있다."""
    return ("가전 AS 상담 통화입니다. 용어: " + ", ".join(vocab[:limit]) + ".") if vocab else ""


# ── 엔진 ─────────────────────────────────────────────────────────────────────
def engines() -> dict[str, Any]:
    s = get_settings()
    return {"openai": bool(s.stt_url), "local": s.voice_stt_local_model, "default": default_engine()}


def default_engine() -> str:
    s = get_settings()
    if s.voice_stt_engine != "auto":
        return s.voice_stt_engine
    return "openai" if s.stt_url else "local"


@lru_cache(maxsize=2)
def _local(model: str):
    from transformers import pipeline  # 무거워 쓸 때만

    return pipeline("automatic-speech-recognition", model=model, device=-1)


def transcribe(x: np.ndarray, engine: str | None = None, prompt: str = "") -> dict[str, Any]:
    """→ {"text", "seconds", "rtf"}. rtf(실시간 계수) = 인식 시간 / 소리 길이 — 1 보다 작아야 말하는 속도를 따라간다."""
    eng = engine or default_engine()
    t = time.perf_counter()
    s = get_settings()
    if eng == "openai":
        if not s.stt_url:
            raise ValueError("STT_URL 이 설정되지 않았습니다")
        data = {"model": s.stt_model, "language": "ko"} | ({"prompt": prompt} if prompt else {})
        r = httpx.post(
            s.stt_url.rstrip("/") + "/audio/transcriptions", files={"file": ("a.wav", audio.to_wav(x), "audio/wav")}, data=data, timeout=120
        )
        r.raise_for_status()
        text = (r.json() or {}).get("text", "")
    elif eng == "local":
        p = _local(s.voice_stt_local_model)
        kw: dict[str, Any] = {"language": "ko", "task": "transcribe"}
        if prompt:
            kw["prompt_ids"] = p.tokenizer.get_prompt_ids(prompt, return_tensors="pt")
        text = p({"raw": x, "sampling_rate": audio.SR}, generate_kwargs=kw)["text"]
        if prompt and text.strip().startswith(prompt.strip()):  # 판에 따라 앞 문맥이 결과에 섞여 나온다
            text = text.strip()[len(prompt.strip()) :]
    else:
        raise ValueError(f"알 수 없는 인식 엔진: {eng}")
    sec = time.perf_counter() - t
    return {"text": text.strip(), "engine": eng, "seconds": round(sec, 3), "rtf": round(sec / max(0.01, len(x) / audio.SR), 3)}


# ── 정확도 ───────────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"[\s.,!?·~\-\"'“”‘’()]", "", s or "").upper()


def cer(ref: str, hyp: str) -> float:
    """글자 오류율(띄어쓰기 · 문장부호 제외) — 한국어는 띄어쓰기가 사람마다 달라 낱말 오류율보다 글자 기준이 맞다."""
    r, h = _norm(ref), _norm(hyp)
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, a in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, b in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b))
        prev = cur
    return round(prev[-1] / len(r), 4)


def term_hits(ref: str, hyp: str, vocab: list[str]) -> tuple[int, int]:
    """정답 글에 나온 사전 용어 중 인식 결과에도 같은 표기로 나온 수 — 오류 코드 · 모델명 하나가 틀리면 검색 전체가 틀린다."""
    terms = [t for t in vocab if _norm(t) in _norm(ref)]
    return sum(1 for t in terms if _norm(t) in _norm(hyp)), len(terms)


def evaluate(items: list[dict[str, Any]], engines_: list[str], vocab: list[str], progress=lambda f, m: None) -> dict[str, Any]:
    """items: [{"audio": np.ndarray, "ref", "id"}]. 엔진마다 (사전 없음 · 앞 문맥만 · 앞 문맥 + 표기 복원)."""
    out = []
    prompt = vocab_prompt(vocab)
    variants = [("plain", "", False), ("prompt", prompt, False), ("prompt+restore", prompt, True)] if vocab else [("plain", "", False)]
    total = len(engines_) * len(variants) * len(items)
    k = 0
    for eng in engines_:
        for name, pr, restore in variants:
            rows, secs, dur = [], 0.0, 0.0
            hit = n_terms = 0
            for it in items:
                progress(k / max(1, total), f"{eng} · {name} · {it['id']}")
                k += 1
                try:
                    r = transcribe(it["audio"], eng, pr)
                except (ValueError, httpx.HTTPError, OSError) as exc:
                    out.append({"engine": eng, "variant": name, "status": "error", "error": str(exc)[:300]})
                    break
                hyp = restore_terms(r["text"], vocab)[0] if restore else r["text"]
                h, n = term_hits(it["ref"], hyp, vocab)
                hit, n_terms = hit + h, n_terms + n
                secs, dur = secs + r["seconds"], dur + len(it["audio"]) / audio.SR
                rows.append({"id": it["id"], "ref": it["ref"], "hyp": hyp, "cer": cer(it["ref"], hyp), "terms": [h, n]})
            else:
                out.append({"engine": eng, "variant": name, "status": "ok", "cer": round(float(np.mean([x["cer"] for x in rows])), 4) if rows else None,
                            "term_acc": round(hit / n_terms, 4) if n_terms else None, "n_terms": n_terms, "rtf": round(secs / dur, 3) if dur else None,
                            "rows": rows})  # fmt: skip
    return {"n": len(items), "vocab": vocab[:60], "results": out}
