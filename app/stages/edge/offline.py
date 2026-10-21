"""ED4 오프라인 동작: 기기 안의 팩 · 모델로 무엇이 되고 무엇을 연결될 때로 미루는지(기능 범위), 그리고 기기에서 묻기 흉내.

기기에서 묻기는 서버가 팩 폴더를 기기와 똑같이 읽어 실행한다(같은 파일 · 같은 검색 코드) — 실제 기기 없이 오프라인 동작을 재 보려고.
순서: 자주 묻는 답(캐시, 근거가 모두 팩 안) → 팩 검색 → 기기 LLM 이 있으면 근거로 답, 없으면 근거만 보여 줌.
서버가 꼭 필요한 일(사진 진단 · 법령 조회 · 지식 그래프 · 팩 밖 자료)은 거절하지 않고 '미룬 요청'으로 대기열에 넣는다 —
연결되면 올리고(ED5) 서버가 처리해 다음 동기화 때 결과를 돌려준다. 사용자에게는 지금 안 되는 이유와 언제 되는지를 함께 보인다.
"""

from typing import Any

# 서버가 필요한 기능 — 오프라인이면 미룬다. 기기 프로필(vision)과 팩 내용으로 일부는 기기에서 될 수 있다.
FEATURES = [
    ("search", "자료 검색", "팩"),
    ("faq", "자주 묻는 답", "팩 캐시"),
    ("answer", "답변 생성", "기기 LLM"),
    ("photo", "사진 진단", "비전 LLM"),
    ("law", "법령 · 조문 조회", "서버(국가법령정보 API)"),
    ("graph", "지식 그래프 질의", "서버(그래프 DB)"),
    ("fresh", "최신 자료", "동기화"),
]


def capabilities(
    manifest: dict[str, Any] | None, profile: dict[str, Any], llm: dict[str, Any] | None, age_hours: float | None, stale_hours: float
) -> list[dict[str, Any]]:
    """기능마다 ok(기기에서 됨) · defer(연결될 때 서버로) · no(이 기기 · 팩으로는 안 됨)와 이유."""
    out = []
    for key, label, needs in FEATURES:
        if key == "search":
            st, why = ("ok", f"팩 v{manifest['version']} · 청크 {manifest['n_chunks']}개") if manifest else ("no", "기기에 팩이 없음")
        elif key == "faq":
            n = (manifest or {}).get("n_cache", 0)
            st, why = ("ok", f"검증된 답 {n}개") if n else ("no", "팩에 담긴 캐시 없음(같은 모델 · 근거가 팩 안인 답만 담김)")
        elif key == "answer":
            st, why = (
                ("ok", f"{llm['name']} ({llm['ram_gb']}GB)") if llm else ("defer", "예산 안의 LLM 없음 — 근거만 보이고 답은 연결될 때")
            )
        elif key == "photo":
            ok = llm and llm.get("vision") and profile.get("vision")
            st, why = ("ok", "비전 LLM + 기기 카메라") if ok else ("defer", "사진은 기기에 두고 연결되면 진단 요청(원본은 정책에 따라)")
        elif key == "fresh":
            if age_hours is None:
                st, why = "no", "동기화 기록 없음"
            else:
                st, why = (
                    ("ok", f"마지막 동기화 {age_hours:.0f}시간 전")
                    if age_hours <= stale_hours
                    else ("defer", f"{age_hours:.0f}시간 전 자료 — 기준 {stale_hours:.0f}시간 넘음, 답에 '자료 기준 시각'을 함께")
                )
        else:
            st, why = "defer", f"{needs} 필요"
        out.append({"key": key, "label": label, "needs": needs, "status": st, "reason": why})
    return out


def needs_server(question: str) -> str | None:
    """질문 자체가 서버 기능을 요구하는지(대기열로 보낼 종류). 규칙이 단순한 이유: 기기에서 LLM 판정을 부를 여유가 없다."""
    q = question.replace(" ", "")
    if any(w in q for w in ("법령", "시행령", "개정", "판례")) and any(w in q for w in ("최신", "현행", "바뀐", "개정")):
        return "law"
    if any(w in q for w in ("몇건", "몇개의판례", "인용한", "관계")):
        return "graph"
    return None


def answer_offline(
    pack_hit: dict[str, Any] | None, results: list[dict[str, Any]], has_llm: bool, kind: str | None, min_score: float = 0.35
) -> dict[str, Any]:
    """기기에서 낼 수 있는 결과를 고른다. LLM 호출은 부르는 쪽(api)이 한다 — 여기서는 무엇을 할지만 정한다."""
    if pack_hit:
        return {"mode": "faq", "answer": pack_hit["answer"], "sources": pack_hit.get("sources", []), "similarity": pack_hit["similarity"]}
    if kind:
        return {
            "mode": "defer",
            "defer": kind,
            "reason": dict((k, n) for k, _, n in FEATURES)[kind] + " 필요 — 연결되면 보냄",
            "sources": results,
        }
    if not results or results[0]["score"] < min_score:
        return {
            "mode": "defer",
            "defer": "question",
            "reason": "팩 안에서 근거를 찾지 못함 — 서버 전체 자료로 연결되면 다시 물음",
            "sources": results,
        }
    return {"mode": "answer" if has_llm else "sources", "sources": results}
