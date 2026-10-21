"""분석용 DB: 앱 DB 를 직접 열지 않고 분석 전용 SQLite 파일(data/analytics/<이름>.db)을 만든다.

왜 따로 만드나: 앱 DB 에는 고객 이름 · 대화 원문 · 요청 기록 해시 사슬이 함께 있다. LLM 이 만든 SQL 을 그 DB 에 돌리면 읽기 전용이어도
개인정보 열을 읽을 수 있고, 무거운 질의가 서비스를 느리게 한다. 분석에 필요한 열만 옮긴 파일을 읽기 전용으로 연다.

- demo: 정해진 씨앗으로 만든 AS 접수 자료(제품 · 문의 · 티켓). 날짜는 2026-04-01 ~ 2026-09-30 고정 — 평가 질문의 정답 SQL 이 '지난달' 같은
  상대 날짜에 기대지 않고 언제 돌려도 같은 답을 내게.
- app: 앱의 AS 상담 기록 · 요청 기록에서 분석용 열만(고객 이름 · 대화 원문 · 질문 글 제외).

실행은 guard.connect(읽기 전용 URI + query_only + 허가 콜백 + 시간 · 행 상한)로만 한다.
"""

import json
import random
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import AsSession, Trace

PRESETS = Path(__file__).parent / "presets"
START, END = date(2026, 4, 1), date(2026, 9, 30)


def root() -> Path:
    d = get_settings().data_dir / "analytics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_of(name: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", name):
        raise ValueError("자료 이름은 영문 · 숫자 · _ · - 만")
    return root() / f"{name}.db"


def preset(name: str) -> Any:
    return json.loads((PRESETS / name).read_text(encoding="utf-8"))


DEMO_DDL = """
CREATE TABLE products (model TEXT PRIMARY KEY, kind TEXT NOT NULL, released TEXT NOT NULL);
CREATE TABLE inquiries (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, product_model TEXT NOT NULL REFERENCES products(model),
  channel TEXT NOT NULL, intent TEXT NOT NULL, code TEXT, urgency TEXT NOT NULL, resolved INTEGER NOT NULL, satisfaction INTEGER,
  handled_by TEXT NOT NULL, customer_phone TEXT);
CREATE TABLE tickets (id INTEGER PRIMARY KEY, inquiry_id INTEGER NOT NULL REFERENCES inquiries(id), created_at TEXT NOT NULL, reason TEXT NOT NULL,
  status TEXT NOT NULL, visit_date TEXT, revisit INTEGER NOT NULL);
"""


def build_demo(name: str, n: int = 2000, seed: int = 7) -> dict[str, Any]:
    """예시 AS 자료. 분포에 일부러 차이를 둔다(WM-200 E4 가 많음 · 건조기 만족도가 낮음 · 9월에 접수가 늚) — 질문의 답이 고르게 같지 않게."""
    rnd = random.Random(seed)
    p = path_of(name)
    p.unlink(missing_ok=True)
    con = sqlite3.connect(p)
    con.executescript(DEMO_DDL)
    products = [("WM-100", "세탁기", "2024-03-01"), ("WM-200", "세탁기", "2025-02-15"), ("DR-300", "건조기", "2025-06-01"),
                ("DW-400", "식기세척기", "2025-09-10"), ("WM-500", "세탁기", "2026-05-20")]  # fmt: skip
    con.executemany("INSERT INTO products VALUES (?,?,?)", products)
    codes = {"세탁기": ["E4", "E1", "OE", "UE", "IE"], "건조기": ["D80", "HE", "TE"], "식기세척기": ["E4", "E1", "LE"]}
    kind = {m: k for m, k, _ in products}
    days = (END - START).days + 1
    tickets = []
    for i in range(1, n + 1):
        d = START + timedelta(days=min(days - 1, int(days * rnd.random() ** 0.8)))  # 뒤로 갈수록 많게(9월 증가)
        m = rnd.choices([x[0] for x in products], weights=[3, 5, 3, 2, 2])[0]
        if m == "WM-500" and d < date(2026, 5, 20):
            m = "WM-200"  # 출시 전 접수는 없다
        intent = rnd.choices(["고장", "사용법", "배송", "환불", "설치"], weights=[50, 22, 10, 8, 10])[0]
        code = None
        if intent == "고장" and rnd.random() < 0.75:
            cs = codes[kind[m]]
            code = "E4" if (m == "WM-200" and rnd.random() < 0.45) else rnd.choice(cs)
        urgency = "safety" if rnd.random() < 0.02 else "high" if intent == "고장" and rnd.random() < 0.25 else "normal"
        handled = "agent" if urgency != "normal" or rnd.random() < 0.3 else "auto"
        resolved = int(rnd.random() < (0.55 if intent == "고장" else 0.85) - (0.15 if kind[m] == "건조기" else 0))
        sat = (
            None
            if rnd.random() < 0.35
            else max(1, min(5, round(rnd.gauss(4.0 if resolved else 2.4, 0.8) - (0.6 if kind[m] == "건조기" else 0))))
        )
        ts = datetime(d.year, d.month, d.day, rnd.randint(8, 20), rnd.randint(0, 59)).isoformat(sep=" ")
        phone = f"010-{rnd.randint(1000, 9999)}-{rnd.randint(1000, 9999)}"  # 개인정보 열 — 권한 시험용(분석가에게는 막힘)
        con.execute("INSERT INTO inquiries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (i, ts, m, rnd.choices(["chat", "phone", "photo"], weights=[5, 4, 1])[0], intent, code, urgency, resolved, sat, handled, phone))  # fmt: skip
        if not resolved and intent in ("고장", "설치"):
            visit = d + timedelta(days=rnd.randint(1, 6))
            status = "closed" if visit < END - timedelta(days=5) else rnd.choice(["open", "visit"])
            tickets.append((i, (d + timedelta(hours=1)).isoformat(), "자동 응답으로 해결 안 됨" if handled == "auto" else "상담원 접수", status,
                            visit.isoformat() if status != "open" else None, int(status == "closed" and rnd.random() < (0.3 if code == "E4" else 0.12))))  # fmt: skip
    con.executemany("INSERT INTO tickets (inquiry_id, created_at, reason, status, visit_date, revisit) VALUES (?,?,?,?,?,?)", tickets)
    con.commit()
    con.close()
    return info(name)


def build_from_app(db: Session, name: str) -> dict[str, Any]:
    """앱 기록에서 분석용 열만. 고객 이름 · 대화 원문 · 질문 · 답 글은 옮기지 않는다."""
    p = path_of(name)
    p.unlink(missing_ok=True)
    con = sqlite3.connect(p)
    con.executescript("""CREATE TABLE as_sessions (id TEXT PRIMARY KEY, created_at TEXT, collection_id INTEGER, product_model TEXT, channel TEXT,
      intent TEXT, urgency TEXT, status TEXT, resolved INTEGER, satisfaction INTEGER, n_messages INTEGER, ticket_reason TEXT);
      CREATE TABLE requests (id INTEGER PRIMARY KEY, created_at TEXT, kind TEXT, route TEXT, model TEXT, collection_id INTEGER, total_ms REAL,
      tokens_in INTEGER, tokens_out INTEGER, cost REAL, status TEXT, supported_ratio REAL);""")  # fmt: skip
    for s in db.scalars(select(AsSession)):
        con.execute("INSERT INTO as_sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (s.id, s.created_at.isoformat(sep=" ", timespec="seconds"), s.collection_id, s.product_model, s.channel, s.intent, s.urgency, s.status,
                     None if s.resolved is None else int(s.resolved), s.satisfaction, len(s.messages or []), (s.ticket or {}).get("reason")))  # fmt: skip
    for t in db.scalars(select(Trace).order_by(Trace.id.desc()).limit(50000)):
        con.execute("INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (t.id, t.created_at.isoformat(sep=" ", timespec="seconds"), t.kind, t.route, t.model, t.collection_id, t.total_ms, t.tokens_in, t.tokens_out,
                     t.cost, t.status, (t.verify or {}).get("supported_ratio")))  # fmt: skip
    con.commit()
    con.close()
    return info(name)


def info(name: str) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{path_of(name)}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {"name": name, "tables": {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}}
    finally:
        con.close()


def listing() -> list[dict[str, Any]]:
    return [info(p.stem) for p in sorted(root().glob("*.db"))]
