"""DA1 스키마 연결 · DA2 의미 계층(지표 정의).

스키마 카드: 표 · 열 설명(프리셋) + 실제 자료에서 뽑은 예시 값(글자 열은 자주 나오는 값 5개). 예시 값이 있어야 LLM 이 'E4' 를 code 열에서,
'건조기' 를 products.kind 에서 찾는다 — 열 이름만으로는 값의 모양을 모른다.

연결: 질문 낱말 → 동의어 사전(프리셋) · 열 설명 · 예시 값과 겹침으로 표 · 열 점수. 연결된 표와 그 표에 외래 키로 이어진 표만 맥락에 넣는다
(표가 많으면 전체 스키마를 다 넣을 수 없다). 연결 정확도는 정답 SQL 이 쓰는 표를 모두 골랐는지(재현율)로 잰다.

의미 계층: 지표('해결률' · '재방문율')를 SQL 식으로 고정해 두고, LLM 은 {지표, 차원, 필터, 기간} JSON 만 고른다 → 정해진 규칙으로 SQL 을
만든다(compile). 같은 지표가 질문 · 사람마다 다르게 계산되지 않게 하려는 것이고, 직접 SQL 생성과 정확도를 비교한다.
"""

import re
import sqlite3
from pathlib import Path
from typing import Any

from app.core import llm
from app.stages.rag import evaluation


def cards(path: Path, meta: dict[str, Any], pii: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """표마다 열 · 설명 · 예시 값. 개인정보 열은 예시 값을 뽑지 않는다(맥락에 실제 번호가 들어가지 않게)."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    pii = pii if pii is not None else meta.get("pii", {})
    try:
        out = {}
        for t, td in meta["tables"].items():
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
            fks = [(r[3], r[2], r[4]) for r in con.execute(f'PRAGMA foreign_key_list("{t}")')]
            cs = []
            for c in cols:
                ex: list[Any] = []
                if c not in pii.get(t, []):
                    ex = [
                        r[0]
                        for r in con.execute(
                            f'SELECT "{c}", COUNT(*) n FROM "{t}" WHERE "{c}" IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 5'
                        )
                    ]
                cs.append({"name": c, "desc": td["columns"].get(c, ""), "examples": ex, "pii": c in pii.get(t, [])})
            out[t] = {"desc": td["desc"], "columns": cs, "fks": [{"column": a, "ref": f"{b}.{c}"} for a, b, c in fks]}
        return out
    finally:
        con.close()


def card_text(cs: dict[str, Any], tables: list[str] | None = None, hide_pii: bool = True) -> str:
    lines = []
    for t, c in cs.items():
        if tables is not None and t not in tables:
            continue
        lines.append(f"표 {t} — {c['desc']}")
        for col in c["columns"]:
            if col["pii"] and hide_pii:
                continue  # 권한이 없는 열은 아예 보여 주지 않는다 — 보이면 LLM 이 쓰려다 막힌다
            ex = f" 예: {', '.join(map(str, col['examples'][:5]))}" if col["examples"] else ""
            lines.append(f"  - {col['name']}: {col['desc']}{ex}")
        for fk in c["fks"]:
            lines.append(f"  * {fk['column']} → {fk['ref']}")
    return "\n".join(lines)


def link(question: str, cs: dict[str, Any], synonyms: dict[str, list[str]], top: int = 2) -> dict[str, Any]:
    """→ {"tables", "columns", "scores"}. 고른 표 + 외래 키로 이어진 표."""
    q = question or ""
    qg = evaluation.grams(q, 2)
    tscore: dict[str, float] = {t: 0.0 for t in cs}
    cscore: dict[str, float] = {}
    for word, targets in synonyms.items():
        if word in q:
            for x in targets:
                t, _, c = x.partition(".")
                tscore[t] = tscore.get(t, 0) + 2
                if c:
                    cscore[x] = cscore.get(x, 0) + 2
    for t, c in cs.items():
        tscore[t] += len(qg & evaluation.grams(c["desc"], 2)) * 0.2
        for col in c["columns"]:
            key = f"{t}.{col['name']}"
            s = len(qg & evaluation.grams(col["desc"], 2)) * 0.1
            s += sum(1.5 for e in col["examples"] if isinstance(e, str) and len(e) >= 2 and e in q)  # 질문에 값이 그대로 — 'E4' · '건조기'
            if s:
                cscore[key] = cscore.get(key, 0) + s
                tscore[t] += s
    ranked = sorted((t for t in tscore if tscore[t] > 0), key=lambda t: -tscore[t])[:top] or [max(cs, key=lambda t: len(cs[t]["columns"]))]
    picked = list(ranked)
    for t in ranked:  # 외래 키로 이어진 표 — 조인할 수 있게
        for fk in cs[t]["fks"]:
            ref = fk["ref"].split(".")[0]
            if ref not in picked:
                picked.append(ref)
    return {
        "tables": picked,
        "columns": sorted(cscore, key=lambda k: -cscore[k])[:8],
        "scores": {t: round(s, 2) for t, s in tscore.items()},
    }


def tables_in(sql: str, names: list[str]) -> set[str]:
    return {t for t in names if re.search(rf"\b{re.escape(t)}\b", sql, re.I)}


# ── DA2 의미 계층 ────────────────────────────────────────────────────────────
PLAN_SYSTEM = (
    "업무 지표 정의 중에서 질문에 맞는 것을 고릅니다. 반드시 JSON 만: "
    '{"metric": 지표 이름, "dimensions": [차원 이름…], "filters": {필터 이름: 값}, "date_from": "YYYY-MM-DD" 또는 null, "date_to": "YYYY-MM-DD"(포함 안 함) 또는 null, '
    '"order": "desc"|"asc"|null, "limit": 수 또는 null}. 정의에 없는 지표 · 차원은 쓰지 않습니다. '
    # 차원 규칙이 없으면 '전체 접수 건수'에도 월을, 해결률에는 차원 8개를 모두 붙여 한 숫자를 묻는 질문이 표가 됐다(실측) — 예를 들어 막는다
    "dimensions 는 질문이 '…별'로 나눠 달라고 할 때만 넣고, 한 숫자를 묻는 질문(전체 · 몇 건 · 비율은?)은 빈 목록 [] 입니다. "
    "질문에 나온 조건(의도 · 모델 · 채널 등)은 dimensions 가 아니라 filters 에 넣습니다."
)


def plan(cfg: llm.LLMConfig, question: str, sem: dict[str, Any]) -> dict[str, Any]:
    # 지표를 '- 지표 이름: 설명'으로 나열했더니 LLM 이 '지표 접수 건수'처럼 머리말까지 이름으로 옮겨, 모든 계획이 '정의에 없는 지표'가 됐다
    # (실측 24문항 모두) — 이름만 줄에 두고, 컴파일에서도 머리말을 떼어 낸다
    defs = "지표:\n" + "\n".join(f"- {k}: {v['desc']}" for k, v in sem["metrics"].items())
    defs += "\n차원: " + ", ".join(sem["dimensions"]) + "\n필터: " + ", ".join(sem["filters"])
    data, _ = llm.chat_json(cfg, PLAN_SYSTEM, f"[정의]\n{defs}\n\n[질문]\n{question}", max_tokens=200, temperature=0.0)
    return data if isinstance(data, dict) else {}


def _lit(v: Any) -> str:
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def compile_plan(p: dict[str, Any], sem: dict[str, Any]) -> str:
    """계획 → SQL. 정의에 없는 이름은 오류 — LLM 이 지표를 지어내면 SQL 을 만들지 않는다."""
    name = str(p.get("metric") or "").strip()
    name = name[3:].strip() if name.startswith("지표 ") else name  # 정의 목록의 머리말을 옮겨 쓴 경우(지어낸 이름이 아님)
    p = p | {"metric": name}
    m = sem["metrics"].get(name)
    if m is None:
        raise ValueError(f"정의에 없는 지표: {p.get('metric')}")
    dims = [d for d in p.get("dimensions") or [] if d]
    bad = [d for d in dims if d not in sem["dimensions"]]
    if bad:
        raise ValueError(f"정의에 없는 차원: {bad}")
    sel = [f'{sem["dimensions"][d]} AS "{d}"' for d in dims] + [f'{m["sql"]} AS "{p["metric"]}"']
    where = []
    for k, v in (p.get("filters") or {}).items():
        if k not in sem["filters"]:
            raise ValueError(f"정의에 없는 필터: {k}")
        vals = v if isinstance(v, list) else [v]
        where.append(f"{sem['filters'][k]} IN ({', '.join(_lit(x) for x in vals)})")
    if p.get("date_from"):
        where.append(f"i.created_at >= {_lit(p['date_from'])}")
    if p.get("date_to"):
        where.append(f"i.created_at < {_lit(p['date_to'])}")
    sql = f"SELECT {', '.join(sel)} FROM {sem['base']}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if dims:
        sql += " GROUP BY " + ", ".join(sem["dimensions"][d] for d in dims)
        if p.get("order") in ("asc", "desc"):
            sql += f' ORDER BY "{p["metric"]}" {p["order"].upper()}'
    if isinstance(p.get("limit"), int) and p["limit"] > 0:
        sql += f" LIMIT {min(p['limit'], 1000)}"
    return sql
