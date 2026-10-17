"""한국어 처리: 형태소 기반 BM25 토큰화, 문장 분리 (Kiwi)."""

import re
import threading

_kiwi = None
_lock = threading.Lock()

# BM25 에 쓰는 품사: 명사·고유명사·동사/형용사 어간·어근·외국어·한자·숫자
KEEP_TAGS = ("NNG", "NNP", "VV", "VA", "XR", "SL", "SH", "SN")
_FALLBACK = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9_\-]+|\d+")


def kiwi():
    global _kiwi
    with _lock:
        if _kiwi is None:
            from kiwipiepy import Kiwi

            _kiwi = Kiwi()  # 모델 로드 1~2초, 이후 재사용
        return _kiwi


def _filter(tokens) -> list[str]:
    return [t.form.lower() for t in tokens if t.tag.startswith(KEEP_TAGS) and (len(t.form) > 1 or t.tag in ("SN", "SH"))]


def tokenize(text: str) -> list[str]:
    if not text.strip():
        return []
    try:
        return _filter(kiwi().tokenize(text))
    except Exception:  # Kiwi 를 쓸 수 없으면 정규식으로 대체
        return [t.lower() for t in _FALLBACK.findall(text)]


def tokenize_many(texts: list[str]) -> list[list[str]]:
    """여러 문서를 한 번에 (Kiwi 내부 병렬 처리)."""
    if not texts:
        return []
    try:
        return [_filter(toks) for toks in kiwi().tokenize(texts)]
    except Exception:
        return [tokenize(t) for t in texts]


def split_sentences(text: str) -> list[str]:
    if not text.strip():
        return []
    try:
        return [s.text.strip() for s in kiwi().split_into_sents(text) if s.text.strip()]
    except Exception:
        return [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text) if s.strip()]


# 키워드·주제어용: 명사·고유명사·어근·외국어·한자만 (동사 어간·숫자 제외)
KEYWORD_TAGS = ("NNG", "NNP", "XR", "SL", "SH")


def nouns_many(texts: list[str]) -> list[list[str]]:
    if not texts:
        return []
    try:
        return [[t.form.lower() for t in toks if t.tag.startswith(KEYWORD_TAGS) and len(t.form) > 1] for toks in kiwi().tokenize(texts)]
    except Exception:
        return [[t.lower() for t in _FALLBACK.findall(x) if not t.isdigit()] for x in texts]
