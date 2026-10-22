"""합성 묶음 저장 · 검토(SD3 · SD6): data/synthetic/<이름>.jsonl(만든 질문 · 만든 방법 · 원본 id) + .meta.json(부족 분석 · 거르기 보고 · 검토).

묶음마다 '무엇이 부족해서 · 어떻게 만들고 · 무엇을 뺐고 · 사람이 몇 건을 봤나'를 같이 남긴다. 그래야 학습 생애주기(TL1 · TL2)가
이 묶음을 데이터 출처로 읽을 수 있다. 검토는 표본의 질문마다 '쓸 만함 · 아님'을 받는다. 오류율의 95% 구간 위 끝이 기준(20%)보다
낮으면 묶음을 통과로 본다. 표본 20건에 오류 0건이어도 위 끝은 16% 라, 적은 표본으로 쉽게 통과시키지 않는다.
"""

import json
import re
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.stages.synthetic import make

PASS_UPPER = 0.2


def root() -> Path:
    d = get_settings().data_dir / "synthetic"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", name):
        raise ValueError("묶음 이름은 영문 · 숫자 · _ · - 만")
    return name


def save(name: str, rows: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    _check(name)
    (root() / f"{name}.jsonl").write_text(make.dumps(rows), encoding="utf-8")
    meta = meta | {"name": name, "n": len(rows)}
    (root() / f"{name}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def load(name: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    p = root() / f"{_check(name)}.jsonl"
    if not p.exists():
        raise ValueError(f"묶음이 없습니다: {name}")
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return rows, json.loads((root() / f"{name}.meta.json").read_text(encoding="utf-8"))


def batches() -> list[dict[str, Any]]:
    out = []
    for m in sorted(root().glob("*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        d = json.loads(m.read_text(encoding="utf-8"))
        out.append({k: d.get(k) for k in ("name", "n", "eval_set_id", "split_seed", "short", "review_status")})
    return out


def review(name: str, item_id: str, ok: bool, note: str = "") -> dict[str, Any]:
    _, meta = load(name)
    sample = meta.get("review") or {}
    if item_id not in sample.get("items", {}):
        raise ValueError("검토 표본에 없는 질문입니다")
    sample["items"][item_id] |= {"ok": ok, "note": note[:200]}
    done = [v for v in sample["items"].values() if v.get("ok") is not None]
    bad = sum(not v["ok"] for v in done)
    lo, hi = make.wilson(bad, len(done))
    status = "검토 중" if len(done) < len(sample["items"]) else ("통과" if hi < PASS_UPPER else "반려")
    sample |= {"done": len(done), "bad": bad, "error_ci": [lo, hi]}
    meta |= {"review": sample, "review_status": status}
    (root() / f"{name}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"status": status, "done": len(done), "total": len(sample["items"]), "bad": bad, "error_ci": [lo, hi]}
