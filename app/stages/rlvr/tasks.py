"""RV1 검증 가능한 과제: 정답을 자동으로 확인할 수 있는 과제를 자료에서 만든다(사람 채점 없이 보상을 줄 수 있게).

유형(난이도 순):
- article_title: '근로기준법 제23조의 제목은?' — 정답은 조문 머리의 제목(법령 문서에서 정형 추출)
- article_number: '근로기준법에서 「해고 등의 제한」은 몇 조?' — 정답은 조문 번호
- citation_count: '근로기준법 제23조를 참조조문으로 인용한 판례는 몇 건?' — 정답은 지식 그래프(K5)의 인용 관계 수(집계)
- calc: 위 수치 둘을 더하거나 빼기 — '근로기준법 제23조 · 제24조를 인용한 판례는 모두 몇 건?'(조회 두 번 + 계산)
학습 / 시험을 나누되 시험에만 있는 유형(calc)을 남긴다 — 학습한 유형만 잘하는지(일반화)를 보려고(RV6).
정답 확인은 글자 맞추기가 아니라 정규화한 값으로: 조문 번호는 '제23조' 모양, 수는 숫자만, 제목은 띄어쓰기 · 문장부호를 뺀 글자.
"""

import json
import random
import re
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Document, KgEdge, KgNode
from app.stages.kg.extract import ART_HEAD, law_name
from app.stages.rag.legal import ARTICLE


def root() -> Path:
    d = get_settings().data_dir / "rlvr"
    (d / "tasks").mkdir(parents=True, exist_ok=True)
    (d / "env").mkdir(parents=True, exist_ok=True)
    return d


def _articles(db: Session, collection_id: int) -> list[dict[str, str]]:
    out = []
    for d in db.scalars(select(Document).where(Document.collection_id == collection_id)):
        if ((d.meta or {}).get("source") or {}).get("kind") not in ("statute", None) or "판례" in d.filename:
            continue
        law = law_name(re.sub(r"\.(txt|md)$", "", d.filename))
        for m in ART_HEAD.finditer("\n".join(d.pages or [])):
            if m.group(3) and len(m.group(3)) >= 3:
                no = f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
                out.append({"law": law, "no": no, "title": m.group(3).strip()})
    return out


def _cites(db: Session, graph: str) -> dict[str, int]:
    """조문 키 → 그 조문을 인용한 판례 수(지식 그래프의 CITES 관계)."""
    q = (select(KgNode.key, func.count(KgEdge.id)).join(KgEdge, KgEdge.dst == KgNode.id)
         .where(KgNode.graph == graph, KgNode.label == "Article", KgEdge.type == "CITES").group_by(KgNode.key))  # fmt: skip
    return {k: n for k, n in db.execute(q).all()}


def build(
    db: Session, collection_id: int, graph: str = "legal", n_per_type: int = 30, seed: int = 7, test_ratio: float = 0.3
) -> dict[str, Any]:
    rnd = random.Random(seed)
    arts = _articles(db, collection_id)
    cites = _cites(db, graph)
    tasks: list[dict[str, Any]] = []
    for a in rnd.sample(arts, min(n_per_type, len(arts))):
        tasks.append({"type": "article_title", "q": f"{a['law']} {a['no']}의 제목은?", "answer": a["title"], "kind": "text", "level": 1,
                      "context_query": f"{a['law']} {a['no']}"})  # fmt: skip
    for a in rnd.sample(arts, min(n_per_type, len(arts))):
        tasks.append({"type": "article_number", "q": f"{a['law']}에서 「{a['title']}」은(는) 몇 조인가요?", "answer": a["no"], "kind": "article", "level": 1,
                      "context_query": f"{a['law']} {a['title']}"})  # fmt: skip
    cited = [(k, n) for k, n in cites.items() if n >= 1]
    for k, n in rnd.sample(cited, min(n_per_type, len(cited))):
        tasks.append({"type": "citation_count", "q": f"{k}를 참조조문으로 인용한 판례는 몇 건인가요?", "answer": str(n), "kind": "number", "level": 2,
                      "context_query": k, "tool": "graph_count", "tool_args": {"article": k}})  # fmt: skip
    for _ in range(min(n_per_type, len(cited) // 2)):
        (k1, n1), (k2, n2) = rnd.sample(cited, 2)
        tasks.append({"type": "calc", "q": f"{k1}와 {k2}를 인용한 판례 수를 합치면 몇 건인가요?(판례가 겹치면 두 번 셉니다)", "answer": str(n1 + n2), "kind": "number",
                      "level": 3, "context_query": f"{k1} {k2}", "tool": "graph_count", "tool_args": {"article": [k1, k2]}})  # fmt: skip
    for i, t in enumerate(tasks):
        t["id"] = f"t{i + 1}"
    train_types = {"article_title", "article_number", "citation_count"}
    train, test = [], []
    for t in tasks:
        if t["type"] not in train_types:
            test.append(t)  # 학습에 없는 유형 — 일반화 확인용
        else:
            (test if rnd.random() < test_ratio else train).append(t)
    return {"collection_id": collection_id, "graph": graph, "train": train, "test": test,
            "counts": {k: sum(t["type"] == k for t in tasks) for k in ("article_title", "article_number", "citation_count", "calc")}}  # fmt: skip


def save(name: str, ts: dict[str, Any]) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", name):
        raise ValueError("과제 이름은 영문 · 숫자 · _ · - 만")
    (root() / "tasks" / f"{name}.json").write_text(json.dumps(ts | {"name": name}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"name": name, "train": len(ts["train"]), "test": len(ts["test"]), "counts": ts["counts"]}


def load(name: str) -> dict[str, Any]:
    p = root() / "tasks" / f"{name}.json"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", name) or not p.exists():
        raise ValueError(f"과제가 없습니다: {name}")
    return json.loads(p.read_text(encoding="utf-8"))


def listing() -> list[dict[str, Any]]:
    out = []
    for p in sorted((root() / "tasks").glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append({"name": d["name"], "train": len(d["train"]), "test": len(d["test"]), "counts": d.get("counts")})
    return out


# ── 정답 확인 ───────────────────────────────────────────────────────────────
FINAL = re.compile(r"정답\s*[:：]\s*(.+)")


def final_of(text: str) -> str | None:
    """마지막 '정답: …' 줄 — 형식 보상과 정답 확인이 같은 곳을 본다(본문 중간의 숫자를 정답으로 잘못 읽지 않게)."""
    hits = FINAL.findall(text or "")
    return hits[-1].strip() if hits else None


def _norm_text(s: str) -> str:
    return re.sub(r"[\s「」『』\"'().,·ㆍ]", "", s or "")


def verify(task: dict[str, Any], text: str) -> dict[str, Any]:
    f = final_of(text)
    if f is None:
        return {"correct": False, "final": None, "why": "'정답:' 줄이 없음"}
    if task["kind"] == "number":
        nums = re.findall(r"\d+", f.replace(",", ""))
        return {"correct": bool(nums) and nums[0] == task["answer"], "final": f, "candidates": len(nums)}
    if task["kind"] == "article":
        m = ARTICLE.search(f)
        got = (f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")) if m else None
        return {"correct": got == task["answer"], "final": f, "candidates": len(ARTICLE.findall(f))}
    return {
        "correct": _norm_text(task["answer"]) in _norm_text(f) and len(_norm_text(f)) <= len(_norm_text(task["answer"])) * 2 + 4,
        "final": f,
    }
