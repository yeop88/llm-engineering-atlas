"""DA3 SQL 생성 · DA4 실행 검증 · 고치기 · DA5 결과 해석 · 차트.

생성: 연결된 스키마 카드 + 예시 질문-SQL + 방언(SQLite: 날짜는 글자 비교 · substr, ILIKE 없음) + 질문 → SQL 하나.
실행 검증: 읽기 전용 실행 → (1) SQL 오류 (2) 빈 결과 (3) 상식 밖 값(음수 건수 · 100 넘는 백분율 · 모두 NULL) 이면 그 사실을 붙여
다시 만든다(상한 max_tries). Text2Cypher 실측에서 실행 검증 재시도로 정확 일치가 40 → 53% 로 오른 것과 같은 방식이다.
빈 결과가 늘 틀린 것은 아니라(조건에 맞는 것이 정말 없을 수 있음) 한 번만 다시 묻는다.

해석: 결과 표 → 문장. 숫자는 결과에서만 — 답 글의 수가 결과 표의 수(또는 그 반올림)인지 검사하고, 아닌 수는 '결과에 없는 수'로 표시한다
(장기 실행의 지어낸 숫자 검사와 같은 원칙). 차트는 '이름 열 하나 + 수 열 하나' 일 때만 막대로.
"""

import re
import sqlite3
from typing import Any

from app.core import llm
from app.stages.analytics import guard

GEN_SYSTEM = (
    "SQLite 질의를 씁니다. 주어진 표 · 열만 쓰고, 날짜는 'YYYY-MM-DD' 글자 비교와 substr 로, 비율은 100.0 * … / … 로 계산합니다. "
    "설명 없이 ```sql 블록 하나만 답합니다."
)


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.+?)```", text or "", re.S | re.I)
    s = m.group(1) if m else (text or "")
    m2 = re.search(r"(?is)\b(WITH|SELECT)\b.*", s)
    return (m2.group(0) if m2 else s).strip().rstrip(";").strip()


def anomalies(res: dict[str, Any]) -> list[str]:
    out = []
    if not res["rows"]:
        return ["결과가 비었습니다 — 값 표기(대소문자 · 띄어쓰기) · 날짜 조건 · 조인 조건을 확인하세요"]
    cols = [c.lower() for c in res["columns"]]
    for j, c in enumerate(cols):
        vals = [r[j] for r in res["rows"]]
        nums = [v for v in vals if isinstance(v, (int, float))]
        if all(v is None for v in vals):
            out.append(f"열 {res['columns'][j]} 이 모두 NULL 입니다")
        if nums and min(nums) < 0 and any(k in c for k in ("count", "n", "건", "수")):
            out.append(f"건수 열 {res['columns'][j]} 에 음수가 있습니다")
        if nums and max(nums) > 100 and any(k in c for k in ("rate", "ratio", "pct", "율", "비율", "%")):
            out.append(f"비율 열 {res['columns'][j]} 이 100 을 넘습니다")
    return out


def generate_and_run(
    cfg: llm.LLMConfig, g: guard.Guarded, question: str, schema_text: str, examples: list[dict[str, str]], max_tries: int = 3
) -> dict[str, Any]:
    ex = "\n\n".join(f"질문: {e['q']}\n```sql\n{e['sql']}\n```" for e in examples)
    base = f"[스키마]\n{schema_text}\n\n[예시]\n{ex}\n\n[질문]\n{question}"
    attempts: list[dict[str, Any]] = []
    feedback = ""
    empty_retried = False
    for k in range(max_tries):
        try:
            r = llm.chat(cfg, GEN_SYSTEM, base + (f"\n\n[앞 시도의 문제]\n{feedback}\n고친 SQL 을 쓰세요." if feedback else ""), 400, 0.0)
        except llm.LLMError as exc:
            attempts.append({"sql": "", "error": f"LLM 오류: {exc}"})
            break
        sql = extract_sql(r["text"])
        a: dict[str, Any] = {"sql": sql, "seconds": r["seconds"]}
        try:
            res = guard.run(g, sql)
        except guard.Blocked as exc:
            a["blocked"] = str(exc)
            attempts.append(a)
            feedback = f"실행이 막혔습니다: {exc}"
            continue
        except sqlite3.Error as exc:
            a["error"] = str(exc)
            attempts.append(a)
            feedback = f"SQL 오류: {exc}"
            continue
        a["result"] = res
        issues = anomalies(res)
        a["issues"] = issues
        attempts.append(a)
        if not issues or k == max_tries - 1:
            break
        if not res["rows"]:
            if empty_retried:
                break  # 정말 없을 수도 있다 — 빈 결과로 두 번 고치지 않는다
            empty_retried = True
        feedback = "실행 결과 점검: " + "; ".join(issues)
    final = next((a for a in reversed(attempts) if "result" in a), None)
    return {"attempts": attempts, "sql": final["sql"] if final else (attempts[-1]["sql"] if attempts else ""), "result": final["result"] if final else None,
            "tries": len(attempts), "ok": final is not None}  # fmt: skip


def run_sql(g: guard.Guarded, sql: str) -> dict[str, Any]:
    try:
        return {"sql": sql, "result": guard.run(g, sql), "ok": True, "attempts": [{"sql": sql}], "tries": 1}
    except (guard.Blocked, sqlite3.Error) as exc:
        return {"sql": sql, "result": None, "ok": False, "attempts": [{"sql": sql, "error": str(exc)}], "tries": 1}


# ── DA5 해석 ─────────────────────────────────────────────────────────────────
EXPLAIN_SYSTEM = "질의 결과 표만 보고 질문에 2~3문장으로 답합니다. 숫자는 표에 있는 값만 쓰고(반올림은 소수 첫째 자리까지), 표에 없는 사실은 말하지 않습니다."
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


def table_text(res: dict[str, Any], limit: int = 30) -> str:
    rows = res["rows"][:limit]
    return " | ".join(res["columns"]) + "\n" + "\n".join(" | ".join("" if v is None else str(v) for v in r) for r in rows)


def number_check(text: str, res: dict[str, Any], question: str) -> dict[str, Any]:
    """답의 수가 결과 표의 수(반올림 · 백분율 바꿈 포함) 또는 질문의 수인가."""
    vals = {float(v) for r in res["rows"] for v in r if isinstance(v, (int, float))}
    vals |= {float(x) for x in NUM.findall(question)} | {float(len(res["rows"]))}
    ok_set = vals | {round(v, 1) for v in vals} | {round(v) for v in vals} | {round(v * 100, 1) for v in vals if abs(v) <= 1}
    found = [float(x) for x in NUM.findall(text.replace(",", ""))]
    bad = sorted({f for f in found if not any(abs(f - v) < 0.051 for v in ok_set)})
    return {"numbers": len(found), "not_in_result": [int(b) if b.is_integer() else b for b in bad], "ok": not bad}


def explain(cfg: llm.LLMConfig, question: str, sql: str, res: dict[str, Any]) -> dict[str, Any]:
    r = llm.chat(cfg, EXPLAIN_SYSTEM, f"[질문]\n{question}\n\n[SQL]\n{sql}\n\n[결과 {len(res['rows'])}행]\n{table_text(res)}", 250, 0.1)
    return {"text": r["text"], "check": number_check(r["text"], res, question), "seconds": r["seconds"]}


def chart(res: dict[str, Any]) -> dict[str, Any] | None:
    """이름 열 하나 + 수 열 하나 · 행 2~30 개면 막대."""
    if not res or len(res["columns"]) != 2 or not 2 <= len(res["rows"]) <= 30:
        return None
    labels, values = [r[0] for r in res["rows"]], [r[1] for r in res["rows"]]
    if not all(isinstance(v, (int, float)) for v in values if v is not None):
        return None
    vmax = max((v for v in values if v is not None), default=0) or 1
    return {"label": res["columns"][1], "bars": [{"name": str(a), "value": b, "max": vmax} for a, b in zip(labels, values, strict=True)]}
