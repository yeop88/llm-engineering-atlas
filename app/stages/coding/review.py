"""CD5 리뷰 · 보안 검사: 테스트가 보지 못하는 것을 diff 에서 본다.

규칙(빠르고 틀리지 않는 것부터):
- 비밀 값: API 키 · 토큰 · 개인 키 모양의 글
- 위험 함수: eval · exec · os.system · subprocess(shell=True) · pickle.loads · yaml.load(안전 로더 없이)
- 테스트 약화: 테스트 파일에서 assert 가 줄거나 skip · xfail 이 붙음 — 테스트를 고쳐 통과시키는 것
- 의존 방향: app/core 가 stages · pipeline 을, stages 가 pipeline 을 가져옴(구조 규칙, tests/test_architecture.py 와 같은 원칙)
- 넓은 예외 삼키기: except: · except Exception: pass
LLM 리뷰는 선택 — 규칙 밖의 논리 문제를 짚게 하고, 지적이 맞는지는 프리셋의 좋은 · 나쁜 diff 로 잰다(정밀도 · 재현율).
"""

import re
from typing import Any

from app.core import llm

RULES = [
    (
        "비밀 값",
        re.compile(
            r"(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC )?PRIVATE KEY|(api[_-]?key|token|secret)\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"])",
            re.I,
        ),
    ),
    ("위험 함수", re.compile(r"\b(eval|exec)\s*\(|os\.system\s*\(|shell\s*=\s*True|pickle\.loads\s*\(|yaml\.load\s*\((?!.*SafeLoader)")),
    ("넓은 예외 삼키기", re.compile(r"except\s*:|except\s+Exception\s*:\s*pass")),
]


def _files(diff: str) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    cur = None
    for ln in diff.splitlines():
        if ln.startswith("+++ b/"):
            cur = ln[6:]
            out[cur] = {"+": [], "-": []}
        elif cur and ln[:1] in "+-" and not ln.startswith(("+++", "---")):
            out[cur][ln[0]].append(ln[1:])
    return out


def check(diff: str) -> list[dict[str, Any]]:
    issues = []
    for f, ch in _files(diff).items():
        added = "\n".join(ch["+"])
        for name, rx in RULES:
            if m := rx.search(added):
                issues.append({"rule": name, "file": f, "match": m.group(0)[:80]})
        if f.startswith("tests/"):
            if sum("assert" in x for x in ch["-"]) > sum("assert" in x for x in ch["+"]):
                issues.append({"rule": "테스트 약화", "file": f, "match": "assert 가 줄었음"})
            if re.search(r"pytest\.(skip|mark\.skip|mark\.xfail)|@unittest\.skip", added):
                issues.append({"rule": "테스트 약화", "file": f, "match": "skip · xfail 추가"})
        if f.startswith("app/core/") and re.search(r"^\s*(from|import) app\.(stages|pipeline|web)", added, re.M):
            issues.append({"rule": "의존 방향", "file": f, "match": "core 가 stages · pipeline · web 을 가져옴"})
        if f.startswith("app/stages/") and not f.endswith("api.py") and re.search(r"^\s*(from|import) app\.(pipeline|web)", added, re.M):
            issues.append({"rule": "의존 방향", "file": f, "match": "단계 로직이 pipeline · web 을 가져옴"})
    return issues


LLM_REVIEW = '코드 변경(diff)을 리뷰합니다. 버그 · 보안 · 테스트 약화 문제가 있으면 {"ok": false, "issues": [한 줄씩]}, 없으면 {"ok": true, "issues": []} 만 JSON 으로.'


def llm_review(cfg: llm.LLMConfig, diff: str) -> dict[str, Any]:
    try:
        data, _ = llm.chat_json(cfg, LLM_REVIEW, diff[-6000:], max_tokens=300, temperature=0.0)
        return {"ok": bool(data.get("ok")), "issues": [str(x) for x in data.get("issues") or []][:8]}
    except (llm.LLMError, ValueError, AttributeError) as exc:
        return {"ok": None, "issues": [], "error": str(exc)[:200]}


def evaluate(cases: list[dict[str, Any]], cfg: llm.LLMConfig | None) -> dict[str, Any]:
    """cases: [{"name", "diff", "bad": bool}] — 규칙 · LLM 리뷰가 나쁜 diff 를 잡고 좋은 diff 는 통과시키는지."""
    rows = []
    for c in cases:
        rule_flag = bool(check(c["diff"]))
        lr = llm_review(cfg, c["diff"]) if cfg else None
        rows.append(
            {
                "name": c["name"],
                "bad": c["bad"],
                "rule": rule_flag,
                "llm": (lr["ok"] is False) if lr and lr["ok"] is not None else None,
                "llm_issues": (lr or {}).get("issues"),
            }
        )

    def pr(key: str) -> dict[str, Any]:
        rs = [r for r in rows if r[key] is not None]
        tp = sum(r[key] and r["bad"] for r in rs)
        fp = sum(r[key] and not r["bad"] for r in rs)
        fn = sum((not r[key]) and r["bad"] for r in rs)
        return {
            "n": len(rs),
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        }

    return {"rule": pr("rule"), "llm": pr("llm") if cfg else None, "rows": rows}
