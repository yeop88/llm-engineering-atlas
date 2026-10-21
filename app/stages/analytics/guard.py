"""DA6 권한 · 안전: 실행하는 쪽에서 막는다 — 프롬프트로 'DELETE 하지 말라'고 하는 것은 방어가 아니다.

겹겹이:
1. 글 검사: 문 하나 · SELECT/WITH 로 시작 · 금지 낱말(ATTACH · PRAGMA · load_extension 등) — 빨리 거절하고 이유를 알려 주려고
2. 연결: 읽기 전용 URI(mode=ro) + PRAGMA query_only
3. 허가 콜백(sqlite3 authorizer): 읽기 외 동작 거부, 역할에 막힌 열(개인정보)을 읽으면 거부 — 글 검사를 피해 간 별칭 · 하위 질의도 여기서 잡힌다
4. 시간 상한(progress handler) · 행 상한(fetchmany)
"""

import re
import sqlite3
import time
from pathlib import Path
from typing import Any

FORBIDDEN = re.compile(r"\b(ATTACH|DETACH|PRAGMA|VACUUM|load_extension|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE)\b", re.I)


class Blocked(ValueError):
    pass


def check_text(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise Blocked("빈 질의")
    if ";" in s:
        raise Blocked("문을 하나만 실행할 수 있습니다")
    if not re.match(r"(?is)^\s*(WITH|SELECT)\b", s):
        raise Blocked("SELECT(또는 WITH) 만 실행할 수 있습니다")
    if m := FORBIDDEN.search(re.sub(r"'[^']*'", "''", s)):  # 문자열 안의 낱말은 보지 않는다
        raise Blocked(f"허용하지 않는 낱말: {m.group(1)}")
    return s


class Guarded:
    """읽기 전용 연결 + 시간 상한 상태(sqlite3.Connection 에는 속성을 붙일 수 없어 감싼다)."""

    def __init__(self, con: sqlite3.Connection, timeout_s: float):
        self.con, self.timeout_s, self.deadline = con, timeout_s, 0.0

    def close(self) -> None:
        self.con.close()


def connect(path: Path, denied_columns: dict[str, set[str]] | None = None, timeout_s: float = 3.0) -> Guarded:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    con.execute("PRAGMA query_only = ON")
    denied = {t.lower(): {c.lower() for c in cs} for t, cs in (denied_columns or {}).items()}
    read_ok = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, getattr(sqlite3, "SQLITE_RECURSIVE", 33)}

    def authorizer(action: int, a1: str | None, a2: str | None, db: str | None, src: str | None) -> int:
        if action not in read_ok:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ and a1 and a2 and a2.lower() in denied.get(a1.lower(), set()):
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and a2 and a2.lower() in ("load_extension", "readfile", "writefile"):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    con.set_authorizer(authorizer)
    g = Guarded(con, timeout_s)

    def tick() -> int:
        return 1 if time.perf_counter() > g.deadline else 0  # 0 이 아니면 실행을 끊는다

    con.set_progress_handler(tick, 10_000)
    return g


def run(g: Guarded, sql: str, max_rows: int = 500) -> dict[str, Any]:
    """→ {"columns", "rows", "truncated", "ms"}. 막히면 Blocked, SQL 오류는 sqlite3.Error 그대로(고치기 단계가 메시지를 씀)."""
    s = check_text(sql)
    g.deadline = time.perf_counter() + g.timeout_s
    t = time.perf_counter()
    try:
        cur = g.con.execute(s)
        rows = cur.fetchmany(max_rows + 1)
    except sqlite3.DatabaseError as exc:
        msg = str(exc)
        if (
            "not authorized" in msg or "prohibited" in msg
        ):  # 판에 따라 허가 콜백 거부 메시지가 다르다(읽기 거부는 'access to … is prohibited')
            raise Blocked("권한이 없는 표 · 열을 읽으려 했습니다(개인정보 열 등)") from exc
        if "interrupted" in msg:
            raise Blocked(f"시간 상한({g.timeout_s}초)을 넘었습니다") from exc
        raise
    cols = [d[0] for d in cur.description or []]
    return {
        "columns": cols,
        "rows": [list(r) for r in rows[:max_rows]],
        "truncated": len(rows) > max_rows,
        "ms": round((time.perf_counter() - t) * 1000, 1),
    }


def test_risky(path: Path, cases: list[dict[str, Any]], denied: dict[str, set[str]]) -> dict[str, Any]:
    """위험 질의 시험: 막혀야 할 것이 막혔나(must_block), 통과해야 할 것이 통과했나."""
    out = []
    con = connect(path, denied, timeout_s=1.0)
    try:
        for c in cases:
            try:
                r = run(con, c["sql"], 50)
                got, why = "ran", f"{len(r['rows'])}행"
            except Blocked as exc:
                got, why = "blocked", str(exc)
            except sqlite3.Error as exc:
                got, why = "error", str(exc)
            ok = (got != "ran") if c["must_block"] else (got == "ran")
            out.append({"name": c["name"], "sql": c["sql"], "must_block": c["must_block"], "got": got, "why": why, "ok": ok})
    finally:
        con.close()
    return {"n": len(out), "passed": sum(r["ok"] for r in out), "cases": out}
