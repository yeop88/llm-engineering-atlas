"""검색 향상 기법: LLM 으로 질의 변형을 만들고, 변형마다 2단계 검색을 돌려 RRF 로 합친다.

설계 이유
- 기법을 검색 엔진(rag.service.search) 안에 넣지 않고 '변형 생성 → 기존 검색 여러 번 → 합치기'로 감쌌다.
  검색 엔진을 건드리지 않으므로 의미 · BM25 · 하이브리드 어느 방식과도 조합되고, 기법을 끈 결과가
  지금까지의 결과와 정확히 같다(비교의 기준선이 흔들리지 않는다).
- 여러 결과는 점수가 아니라 순위로 합친다(RRF). 원 질의와 HyDE 문서의 코사인 점수는 분포가 달라
  점수 합은 한쪽으로 쏠리지만, 순위는 척도와 무관하다 — 하이브리드에서 RRF 를 쓰는 것과 같은 이유.
- 리랭커는 변형별로 돌리지 않고 합친 뒤 '원 질의'로 한 번만 돌린다. 리랭커는 비싸고(CPU 질문당 수십 초),
  최종 판단은 LLM 이 바꾼 문장이 아니라 사용자가 실제로 물은 것에 맞춰야 하기 때문이다.
"""

import threading
import time
from collections import OrderedDict
from typing import Any

from sqlalchemy.orm import Session

from app.core import llm
from app.stages.rag import service
from app.stages.rag.fusion import rrf

TECHNIQUES = {
    "none": "기법 없음 (기준선)",
    "rewrite": "질의 재작성",
    "hyde": "HyDE (가상 문서)",
    "multi": "다중 질의",
}

# 프롬프트는 한국어로 쓰되 '질문과 같은 언어로' 답하게 한다. 한국어 특화지만 다국어 문서도 다루기 때문.
REWRITE_SYSTEM = (
    "당신은 문서 검색 질의를 다듬는 도우미입니다. 사용자의 질문을 문서에서 찾기 좋은 검색 질의 한 줄로 바꾸세요. "
    "구어체 · 상황 설명은 빼고, 핵심 개념과 문서에 쓰였을 법한 공식 용어 · 동의어를 넣으세요. "
    "질문과 같은 언어로, 설명 없이 검색 질의만 출력하세요."
)
HYDE_SYSTEM = (
    "당신은 문서 작성자입니다. 주어진 질문에 답하는 문서의 한 단락을 문서체로 3~5문장 쓰세요. "
    "사실이 정확하지 않아도 되지만, 그런 문서에 실제로 나올 법한 용어와 표현을 쓰세요. "
    "질문과 같은 언어로, 제목 · 설명 없이 단락만 출력하세요."
)
MULTI_SYSTEM = (
    "당신은 문서 검색 질의를 만드는 도우미입니다. 사용자의 질문을 서로 다른 관점 · 표현의 검색 질의 {n}개로 바꾸세요. "
    "같은 뜻의 반복이 아니라 용어 · 범위 · 관점이 달라야 합니다. 질문과 같은 언어로 쓰고 "
    '{{"queries": ["...", "..."]}} 형식의 JSON 만 출력하세요.'
)


class _Cache:
    """LLM 변형 결과 캐시 (프로세스 메모리, LRU).

    조합 평가는 같은 질문을 설정마다(청킹 × 모델 × 방식) 다시 검색하고, 로컬 LLM 은 호출당 수 초가 걸린다.
    변형은 질문 · 기법 · LLM 에만 달려 있으므로 캐시하면 LLM 호출이 '질문 수'로 줄고, 같은 변형으로
    설정끼리 비교하게 되어 LLM 의 무작위성이 설정 간 차이에 섞이지 않는다.
    """

    def __init__(self, size: int = 2048) -> None:
        self.size = size
        self.data: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
        self.lock = threading.Lock()  # 평가 작업(스레드)과 웹 요청이 동시에 쓴다

    def get(self, key: tuple) -> dict[str, Any] | None:
        with self.lock:
            if key in self.data:
                self.data.move_to_end(key)
                return self.data[key]
        return None

    def put(self, key: tuple, value: dict[str, Any]) -> None:
        with self.lock:
            self.data[key] = value
            self.data.move_to_end(key)
            while len(self.data) > self.size:
                self.data.popitem(last=False)

    def clear(self) -> None:
        with self.lock:
            self.data.clear()


cache = _Cache()


def _one_line(text: str) -> str:
    # 작은 모델은 '검색 질의:' 같은 머리말이나 따옴표 · 여러 줄을 붙이곤 한다. 검색어를 오염시키므로 걷어낸다.
    line = next((x.strip() for x in text.splitlines() if x.strip()), "")
    if ":" in line[:12]:
        line = line.split(":", 1)[1].strip()
    return line.strip("\"'“”「」 ")


def generate(technique: str, query: str, cfg: llm.LLMConfig, n: int = 3) -> dict[str, Any]:
    """→ {"variants": [{"text", "role"}], "seconds", "calls", "cached"}. 원 질의는 포함하지 않는다."""
    key = (technique, n, cfg.provider, cfg.model, query)
    if hit := cache.get(key):
        return hit | {"cached": True, "seconds": 0.0, "calls": 0}
    t = time.perf_counter()
    # temperature 0: 같은 질문에 같은 변형이 나와야 평가를 다시 돌렸을 때 재현된다.
    if technique == "rewrite":
        res = llm.chat(cfg, REWRITE_SYSTEM, query, max_tokens=120, temperature=0)
        variants = [{"text": _one_line(res["text"]), "role": "query"}]
    elif technique == "hyde":
        res = llm.chat(cfg, HYDE_SYSTEM, query, max_tokens=400, temperature=0)
        # 가상 '문서'이므로 문서 역할로 인코딩한다 (service.search 의 encode_role 주석 참고).
        variants = [{"text": res["text"].strip(), "role": "document"}]
    elif technique == "multi":
        obj, res = llm.chat_json(cfg, MULTI_SYSTEM.format(n=n), query, max_tokens=400, temperature=0)
        qs = obj.get("queries") if isinstance(obj, dict) else obj
        if not isinstance(qs, list):
            raise llm.LLMError("다중 질의 응답에 queries 목록이 없습니다.")
        seen = {query.strip()}
        variants = []
        for q in qs:  # 원 질의와 같거나 서로 겹치는 변형은 같은 검색을 두 번 세는 셈이라 뺀다
            q = str(q).strip()
            if q and q not in seen:
                seen.add(q)
                variants.append({"text": q, "role": "query"})
        variants = variants[:n]
    else:
        raise ValueError(f"알 수 없는 검색 향상 기법: {technique}")
    variants = [v for v in variants if v["text"]]
    if not variants:
        # 빈 변형으로 조용히 원 질의만 검색하면 '기법 효과 없음'으로 잘못 기록된다. 실패로 드러낸다.
        raise llm.LLMError("LLM 이 질의 변형을 만들지 못했습니다 (빈 응답).")
    out = {"variants": variants, "seconds": round(time.perf_counter() - t, 2), "calls": 1, "cached": False}
    cache.put(key, {"variants": variants})
    return out


def search(db: Session, query: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """cfg 는 service.search 설정 + enhance={technique, keep_original, n, provider, model}. 반환 형식은 service.search 와 같고
    'enhance' 정보(변형 · LLM 시간)가 더 붙는다."""
    enh = cfg.get("enhance") or {}
    technique = enh.get("technique") or "none"
    if technique == "none":
        return service.search(db, query, cfg)
    try:
        lcfg = llm.resolve(enh.get("provider"), enh.get("model"))
        gen = generate(technique, query, lcfg, int(enh.get("n") or 3))
    except llm.LLMError as exc:
        # 호출자들은 RagError 를 검색 실패로 처리한다. LLM 오류도 같은 경로로 보여 주려고 바꿔 던진다.
        raise service.RagError(f"검색 향상({TECHNIQUES[technique]}) 실패: {exc}") from exc

    # 재작성 · HyDE 는 원 질의가 이미 잘 맞는 경우를 망칠 수 있어, 기본으로 원 질의 검색도 함께 합친다.
    # keep_original=False 는 '변형만으로 검색'을 따로 재 보기 위한 선택지다.
    keep = enh.get("keep_original", True)
    searches = ([{"text": query, "role": "query", "name": "original"}] if keep else []) + [
        v | {"name": f"{technique}{i + 1}"} for i, v in enumerate(gen["variants"])
    ]
    top_k = int(cfg.get("top_k", 10))
    cand = max(top_k, int(cfg.get("candidates", 50)))
    # 하위 검색은 리랭커를 끄고 후보 수만큼 받는다. 합친 뒤에 잘라야 변형 하나에만 걸린 문서도 살아남는다.
    sub_cfg = {k: v for k, v in cfg.items() if k != "enhance"} | {"reranker_id": None, "top_k": cand}
    rankings: dict[str, list[tuple[int, float]]] = {}
    by_id: dict[int, dict[str, Any]] = {}
    timings: dict[str, float] = {"llm": gen["seconds"]}
    first: dict[str, Any] = {}
    for s in searches:
        res = service.search(db, s["text"], sub_cfg | {"encode_role": s["role"]})
        first = first or res
        rankings[s["name"]] = [(r["chunk_id"], r["score"]) for r in res["results"]]
        for r in res["results"]:
            by_id.setdefault(r["chunk_id"], r)
        for k, v in res["timings_ms"].items():  # 변형마다 걸린 시간을 단계별로 더해 '향상의 비용'을 보이게 한다
            timings[k] = timings.get(k, 0.0) + v / 1000

    # 검색이 하나뿐(keep_original=False 인 재작성 · HyDE)이어도 같은 RRF 를 거쳐 결과 형식을 맞춘다. 순서는 그대로다.
    fused = rrf(rankings)[:cand]
    reranked = False
    if cfg.get("reranker_id") and fused:
        head = fused[: int(cfg.get("rerank_top", 30))]
        scores = service.rerank_scores(db, query, [by_id[e["id"]]["text"] for e in head], cfg["reranker_id"], timings)
        for i, (e, sc) in enumerate(zip(head, scores, strict=True)):
            e["scores"]["rerank"] = sc
            e["pre_rank"] = i + 1
        fused = sorted(head, key=lambda e: -e["scores"]["rerank"])
        reranked = True

    results = []
    for rank, e in enumerate(fused[:top_k], start=1):
        base = by_id[e["id"]]
        results.append(
            base
            | {
                "rank": rank,
                "score": round(float(e["scores"].get("rerank", e["score"])), 5),
                "scores": {k: round(float(v), 5) for k, v in e["scores"].items()},
                "ranks": e["ranks"] | ({"before_rerank": e["pre_rank"]} if "pre_rank" in e else {}),
            }
        )
    return {
        "mode": first.get("mode", cfg.get("mode")),
        "reranked": reranked,
        "chunk_set_id": first.get("chunk_set_id"),
        "index_id": first.get("index_id"),
        "query_tokens": first.get("query_tokens", []),
        "timings_ms": {k: round(v * 1000, 1) for k, v in timings.items()},
        "total_ms": round(sum(timings.values()) * 1000, 1),
        "candidates": {k: len(v) for k, v in rankings.items()},
        "results": results,
        "enhance": {
            "technique": technique,
            "label": TECHNIQUES[technique],
            "keep_original": keep,
            "variants": [{"name": s["name"], "text": s["text"], "role": s["role"]} for s in searches],
            "llm": lcfg.public(),
            "llm_seconds": gen["seconds"],
            "llm_calls": gen["calls"],
            "cached": gen["cached"],
        },
    }
