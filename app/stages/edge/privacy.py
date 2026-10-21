"""ED6 개인정보 국소 처리: 기기 → 서버 전송 정책(항목별 raw · masked · stats · never)과 서버 쪽 재검사.

기기에서 돌리는 큰 이유가 개인정보인데, 동기화로 올리는 기록 · 피드백이 그 장점을 깨기 쉽다. 그래서 올리기 전에 기기에서
항목마다 정책을 적용하고(prepare), 서버는 받은 것을 다시 검사한다(inspect) — 기기 마스킹을 믿지 않는 이유: 기기 앱 판이
제각각이고 탐지 규칙도 서버보다 늦게 갱신된다. 서버가 새어 들어온 개인정보를 찾으면 원문을 저장하지 않고 가린 값만 남기며
위반을 기록해 그 기기를 표시한다(어느 기기 · 항목에서 새는지).

stats 는 값을 버리고 개수 · 길이 같은 집계만 남긴다(사용 기록), never 는 항목째 뺀다(고객 이름 · 연락처 · 사진 원본).
"""

import copy
from typing import Any

from app.stages.guardrails import pii

RULES = ("raw", "masked", "stats", "never")
DEFAULT_POLICY: dict[str, str] = {
    "question": "masked",  # 질문은 품질 개선에 필요하지만 고객이 이름 · 번호를 섞어 쓴다
    "answer": "masked",
    "feedback": "masked",
    "rating": "raw",
    "customer": "never",  # 이름 · 연락처 · 주소 — 기기 밖으로 나가지 않는다
    "photo": "never",  # 사진 원본은 두고, 진단 결과(label)만
    "label": "raw",
    "usage": "stats",
    "device_log": "stats",
}


def _apply(value: Any, rule: str, stats: dict[str, Any], key: str, report: dict[str, Any]) -> tuple[bool, Any]:
    """(남길지, 값)."""
    if rule == "never":
        report["dropped"].append(key)
        return False, None
    if rule == "stats":
        s = stats.setdefault(key, {"n": 0, "chars": 0})
        s["n"] += 1
        s["chars"] += len(str(value))
        return False, None
    if rule == "masked" and isinstance(value, str):
        masked, hits = pii.mask(value)
        for t, n in pii.counts(hits).items():
            report["masked"][t] = report["masked"].get(t, 0) + n
        return True, masked
    return True, value


def prepare(events: list[dict[str, Any]], policy: dict[str, str] | None = None) -> dict[str, Any]:
    """기기에서 올리기 전에 — 각 기록의 payload 항목에 정책 적용. 정책에 없는 항목은 masked(모르는 것은 가린다)."""
    pol = DEFAULT_POLICY | (policy or {})
    out, stats = [], {}
    report: dict[str, Any] = {"masked": {}, "dropped": []}
    for e in events:
        e = copy.deepcopy(e)
        payload = {}
        for k, v in (e.get("payload") or {}).items():
            keep, val = _apply(v, pol.get(k, "masked"), stats, k, report)
            if keep:
                payload[k] = val
        if payload:
            out.append(e | {"payload": payload})
    report["dropped"] = sorted(set(report["dropped"]))
    return {"events": out, "stats": stats, "report": report, "policy": pol}


def _strings(x: Any, path: str = ""):
    if isinstance(x, str):
        yield path, x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from _strings(v, f"{path}.{k}" if path else k)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _strings(v, f"{path}[{i}]")


def _mask_all(x: Any) -> Any:
    if isinstance(x, str):
        return pii.mask(x)[0]
    if isinstance(x, dict):
        return {k: _mask_all(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_mask_all(v) for v in x]
    return x


def inspect(payload: dict[str, Any], policy: dict[str, str] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """서버가 받은 payload 를 다시 검사 → (저장할 값, 위반). 위반: 남은 개인정보 · 정책상 오면 안 되는 항목(never · stats 인데 값이 옴)."""
    pol = DEFAULT_POLICY | (policy or {})
    violations = []
    for k in payload:
        if pol.get(k) in ("never", "stats"):
            violations.append({"field": k, "type": f"정책 {pol[k]} 항목이 원문으로 옴"})
    for path, s in _strings(payload):
        for t, n in pii.counts(pii.scan(s)).items():
            violations.append({"field": path, "type": t, "count": n})
    clean = {k: v for k, v in payload.items() if pol.get(k) not in ("never", "stats")}
    return (_mask_all(clean) if violations else clean), violations
