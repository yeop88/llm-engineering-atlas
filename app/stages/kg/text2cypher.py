"""K6 Text2Cypher: 질문 → (LLM) Cypher → Neo4j(읽기 전용) → 결과. K1 역량 질문으로 정확도를 잰다.

스키마 설명은 온톨로지(K2)에서 만든다 — 손으로 쓴 설명은 그래프가 바뀌면 어긋난다. 쓰기 쿼리는 그래프 저장소가 EXPLAIN 으로 막고,
실행 오류 · 빈 결과면 그 사실을 알려 다시 쓰게 한다(최대 retries 번). 빈 결과가 맞는 답일 수도 있어 빈 결과 재시도는 한 번만.
"""

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core import llm
from app.stages.kg import ontology

PRESETS = Path(__file__).parent / "presets"
SYSTEM = (
    "당신은 질문을 Cypher(OpenCypher) 읽기 쿼리로 바꾸는 도구입니다. 아래 스키마에 있는 레이블 · 속성 · 관계만 쓰고, 관계 방향을 지킵니다. "
    "MATCH · OPTIONAL MATCH · WHERE · WITH · RETURN · ORDER BY · LIMIT · count/collect 같은 읽기만 쓰고 CREATE · MERGE · DELETE · SET 은 쓰지 않습니다. "
    "결과 열에는 사람이 읽을 이름(key 또는 name)을 돌려줍니다. 별칭(AS 뒤)은 영문으로 씁니다. 관계가 없는 것은 EXISTS { } 하위 쿼리 대신 "
    "패턴 조건으로 씁니다(예: WHERE NOT (a)<-[:CITES]-(:Precedent)). 설명 없이 Cypher 한 개만 출력합니다.\n\n[스키마]\n"
)
# 별칭 · EXISTS 규칙을 둔 이유: 엔진 비교 실측에서 FalkorDB 가 따옴표 없는 한글 별칭('AS 판례명')과 EXISTS { } 하위 쿼리를 문법 오류로
# 거절했다(Neo4j 는 둘 다 받음). 엔진마다 프롬프트를 나누기보다 두 엔진이 모두 받는 공통 문법으로 쓰게 한다.
FEWSHOT = [
    (
        "근로기준법 제23조를 인용한 판례의 사건번호는?",
        "MATCH (p:Precedent)-[:CITES]->(a:Article {key: '근로기준법 제23조'}) RETURN p.case_no",
    ),
    ("최저임금법에 속한 조문은 몇 개인가?", "MATCH (a:Article)-[:PART_OF]->(s:Statute {key: '최저임금법'}) RETURN count(a) AS n"),
]


def cq_preset() -> dict[str, Any]:
    return json.loads((PRESETS / "legal_cq.json").read_text(encoding="utf-8"))


def _clean(text: str) -> str:
    t = (text or "").strip()
    if m := re.search(r"```(?:cypher)?\s*(.+?)```", t, re.S | re.I):
        t = m.group(1)
    return t.strip().rstrip(";")


def generate(lcfg: llm.LLMConfig, question: str, feedback: str = "") -> str:
    shots = "\n".join(f"질문: {q}\nCypher: {c}" for q, c in FEWSHOT)
    user = f"[예시]\n{shots}\n\n[질문]\n{question}" + (f"\n\n[앞선 시도]\n{feedback}\n위 문제를 고쳐 다시 쓰세요." if feedback else "")
    return _clean(llm.chat(lcfg, SYSTEM + ontology.schema_text(), user, 400, 0.0)["text"])


def ask(lcfg: llm.LLMConfig, question: str, run: Callable[[str], dict[str, Any]], retries: int = 2) -> dict[str, Any]:
    """→ {"cypher", "result"|None, "error", "attempts": [...], "seconds"}."""
    t0 = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    feedback = ""
    empty: tuple[str, dict[str, Any]] | None = None  # 빈 결과로 끝난 첫 시도(다시 써도 비면 빈 결과가 답)
    for _ in range(retries + 1):
        q = generate(lcfg, question, feedback)
        try:
            res = run(q)
        except Exception as exc:  # 문법 · 스키마 · 권한 오류 — 메시지를 알려 다시 쓰게
            attempts.append({"cypher": q, "error": str(exc)[:300]})
            feedback = f"Cypher: {q}\n오류: {str(exc)[:300]}"
            if "EXISTS {" in q.upper().replace(
                "EXISTS{", "EXISTS {"
            ):  # FalkorDB 문법 오류 메시지('(' 기대 …)만으로는 소형 모델이 못 고쳤다
                feedback += (
                    "\n이 엔진은 EXISTS { } 하위 쿼리를 지원하지 않습니다. WHERE NOT (a)<-[:CITES]-(:Precedent) 같은 패턴 조건으로 쓰세요."
                )
            continue
        attempts.append({"cypher": q, "rows": len(res["rows"])})
        if not res["rows"] and empty is None:
            empty = (q, res)
            feedback = f"Cypher: {q}\n결과가 비었습니다. 레이블 · key 표기 · 관계 방향을 확인하세요."
            continue
        return {"cypher": q, "result": res, "error": None, "attempts": attempts, "seconds": round(time.perf_counter() - t0, 1)}
    if empty is not None:
        return {"cypher": empty[0], "result": empty[1], "error": None, "attempts": attempts, "seconds": round(time.perf_counter() - t0, 1)}
    return {"cypher": attempts[-1]["cypher"] if attempts else "", "result": None, "error": attempts[-1].get("error") if attempts else "생성 실패",
            "attempts": attempts, "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip


def _norm_rows(res: dict[str, Any] | None) -> set[str]:
    """결과 비교용: 행마다 값들을 글자로 이어 집합으로(열 이름 · 순서 차이는 무시)."""
    if not res:
        return set()
    out = set()
    for row in res["rows"]:
        vals = [json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (list, dict)) else str(v) for v in row]
        out.add("|".join(sorted(vals)))
    return out


def _lenient(gold: dict[str, Any], got: dict[str, Any] | None) -> bool:
    """행 수가 같고, 기대 행마다 값이 모두 어떤 결과 행의 값 안에 들어 있으면(사건번호 ⊂ '임금 (사건번호)') 같은 답으로 본다."""
    if not got or len(gold["rows"]) != len(got["rows"]):
        return False
    rows = [[str(v) for v in r] for r in got["rows"]]
    return all(any(all(any(str(g) in v for v in r) for g in grow) for r in rows) for grow in gold["rows"])


def score(gold: dict[str, Any], got: dict[str, Any] | None) -> dict[str, Any]:
    """정확 일치(행 집합이 같음) · 겹침(Jaccard) · 느슨한 일치(같은 개체를 다른 속성으로). 집계 하나짜리 답은 값이 같으면 일치."""
    a, b = _norm_rows(gold), _norm_rows(got)
    if not a and not b:
        return {"exact": True, "jaccard": 1.0, "lenient": True}
    inter = len(a & b)
    return {"exact": a == b, "jaccard": round(inter / len(a | b), 3) if (a | b) else 0.0, "lenient": a == b or _lenient(gold, got)}
