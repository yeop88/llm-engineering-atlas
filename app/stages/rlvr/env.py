"""RV2 환경 · 도구 시뮬레이터: 학습 중 에이전트가 받는 도구 결과를 실제와 같게, 빠르고 재현 가능하게.

처음 한 번은 실제 도구(검색 · 그래프 집계)를 부르고 결과를 기록해 두고, 다음부터는 기록을 되돌려 준다(record → replay).
학습은 같은 과제를 수십 번 다시 풀어 보므로 매번 실제 검색을 부르면 느리고, 색인 · 그래프가 그사이 바뀌면 같은 과제의 보상이
달라져 학습 신호가 흔들린다. 대신 '환경-실제 차이'를 점검한다: 표본 과제를 다시 실제로 불러 기록과 겹치는 비율 — 낮으면 기록이 낡았다.
"""

import hashlib
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import KgEdge, KgNode
from app.stages.rlvr import tasks as tk

SearchFn = Callable[[str], list[dict[str, Any]]]


def graph_count(db: Session, graph: str, article: str | list[str]) -> dict[str, Any]:
    keys = article if isinstance(article, list) else [article]
    out = {}
    for k in keys:
        out[k] = db.scalar(select(func.count(KgEdge.id)).join(KgNode, KgEdge.dst == KgNode.id)
                           .where(KgNode.graph == graph, KgNode.key == k, KgEdge.type == "CITES")) or 0  # fmt: skip
    return out


class Env:
    def __init__(self, name: str, search: SearchFn, db: Session, graph: str, replay: bool = True):
        self.path = tk.root() / "env" / f"{name}.json"
        self.cache: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8")) if replay and self.path.exists() else {}
        self.search, self.db, self.graph = search, db, graph
        self.hits = self.misses = 0

    def _key(self, kind: str, arg: Any) -> str:
        return hashlib.sha1(f"{kind}:{json.dumps(arg, ensure_ascii=False, sort_keys=True)}".encode()).hexdigest()[:16]

    def observe(self, task: dict[str, Any]) -> dict[str, Any]:
        """과제 → 도구 결과(검색 근거 · 그래프 집계). 같은 과제는 늘 같은 관찰."""
        k = self._key("obs", [task["context_query"], task.get("tool"), task.get("tool_args")])
        if k in self.cache:
            self.hits += 1
            return self.cache[k]
        self.misses += 1
        obs = {
            "docs": [{"filename": r.get("filename"), "text": (r.get("text") or "")[:700]} for r in self.search(task["context_query"])[:4]]
        }
        if task.get("tool") == "graph_count":
            obs["graph_count"] = graph_count(self.db, self.graph, task["tool_args"]["article"])
        self.cache[k] = obs
        return obs

    def save(self) -> None:
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")


def prompt(task: dict[str, Any], obs: dict[str, Any]) -> list[dict[str, str]]:
    docs = "\n\n".join(f"[{i + 1}] ({d['filename']}) {d['text']}" for i, d in enumerate(obs.get("docs") or []))
    tool = f"\n\n[그래프 집계 도구 결과] {json.dumps(obs['graph_count'], ensure_ascii=False)}" if obs.get("graph_count") else ""
    return [{"role": "system", "content": "자료와 도구 결과만 보고 답합니다. 계산이 필요하면 짧게 풀고, 마지막 줄에 '정답: …' 한 줄로 답을 적습니다."},
            {"role": "user", "content": f"[자료]\n{docs}{tool}\n\n[질문]\n{task['q']}"}]  # fmt: skip


def gap_check(name: str, search: SearchFn, db: Session, graph: str, sample: list[dict[str, Any]]) -> dict[str, Any]:
    """기록 vs 지금 실제: 근거 파일 겹침(Jaccard) · 그래프 집계가 같은지."""
    rec, live = Env(name, search, db, graph, replay=True), Env(name + "-live", search, db, graph, replay=False)
    rows = []
    for t in sample:
        a, b = rec.observe(t), live.observe(t)
        fa, fb = {d["filename"] for d in a.get("docs") or []}, {d["filename"] for d in b.get("docs") or []}
        rows.append(
            {
                "id": t["id"],
                "docs_overlap": round(len(fa & fb) / len(fa | fb), 3) if fa | fb else 1.0,
                "graph_same": a.get("graph_count") == b.get("graph_count"),
            }
        )
    n = max(1, len(rows))
    return {"n": len(rows), "docs_overlap": round(sum(r["docs_overlap"] for r in rows) / n, 3), "graph_same": round(sum(r["graph_same"] for r in rows) / n, 3),
            "recorded": rec.hits, "rows": rows[:30]}  # fmt: skip
