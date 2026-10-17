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
    """줄바꿈은 항상 경계로 보고(제목·목록 항목), 각 줄 안에서 Kiwi 로 문장을 나눈다."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    try:
        k = kiwi()
        return [s.text.strip() for ln in lines for s in k.split_into_sents(ln) if s.text.strip()]
    except Exception:
        return [s.strip() for ln in lines for s in re.split(r"(?<=[.!?。])\s+", ln) if s.strip()]


# 키워드·주제어용: 명사·고유명사·어근·외국어·한자만 (동사 어간·숫자 제외)
KEYWORD_TAGS = ("NNG", "NNP", "XR", "SL", "SH")


def nouns_many(texts: list[str]) -> list[list[str]]:
    if not texts:
        return []
    try:
        return [[t.form.lower() for t in toks if t.tag.startswith(KEYWORD_TAGS) and len(t.form) > 1] for toks in kiwi().tokenize(texts)]
    except Exception:
        return [[t.lower() for t in _FALLBACK.findall(x) if not t.isdigit()] for x in texts]


# 명사구의 처음·끝에 오면 뜻이 흐려지는 의존적인 명사
EDGE_STOP = {"이상", "이하", "이내", "이후", "이전", "최근", "경우", "정도", "관련", "가지", "때문"}


def noun_phrases_many(texts: list[str], max_words: int = 3) -> list[list[str]]:
    """키워드 후보: 명사류 1개 또는 이어진 명사류 2~max_words 개 ("임베딩 모델", "사내 문서 검색", "bm25").
    띄어 쓴 한 글자 명사(형태소 분석 오류·"후" 같은 의존 명사)는 구를 끊고, 숫자는 바로 앞에 붙어 있을 때만 잇는다."""
    if not texts:
        return []
    try:
        out = []
        for text, toks in zip(texts, kiwi().tokenize(texts), strict=True):
            runs: list[list] = [[]]
            for t in toks:
                prev = runs[-1][-1] if runs[-1] else None
                gap = t.start - (prev.start + prev.len) if prev else 99
                if t.tag == "SN":
                    ok = prev is not None and gap == 0
                else:
                    ok = t.tag.startswith(KEYWORD_TAGS) and not (t.len == 1 and t.tag == "NNG" and gap != 0)
                if ok and prev is not None and gap <= 1:
                    runs[-1].append(t)
                elif ok:
                    runs.append([t])
                else:
                    runs.append([])
            cands = []
            for run in runs:
                for i in range(len(run)):
                    for j in range(i + 1, min(len(run), i + max_words) + 1):
                        span = run[i:j]
                        if span[0].form in EDGE_STOP or span[-1].form in EDGE_STOP or span[0].tag == "SN":
                            continue
                        if j < len(run) and run[j].tag == "SN":  # "BM25" 를 "bm" 에서 자르지 않는다
                            continue
                        phrase = text[span[0].start : span[-1].start + span[-1].len].lower()
                        if len(phrase.replace(" ", "")) > 1:
                            cands.append(phrase)
            out.append(cands)
        return out
    except Exception:
        return nouns_many(texts)
