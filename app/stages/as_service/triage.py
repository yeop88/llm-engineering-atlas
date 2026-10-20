"""AS2 의도 · 긴급도 분류: 문의 유형으로 처리 경로를 정하고, 안전 관련 문의는 분류기보다 먼저 규칙으로 잡아 사람에게 넘긴다.

- 긴급도: 안전(감전 · 화재 · 연기 · 가스 · 불꽃) > 높음(누수 · 전원 안 켜짐 · 히터 오류) > 보통. 안전은 규칙 — 분류기가 한 번이라도
  틀리면 위험한 문의를 자동 답변하게 되므로 확률 모델에 맡기지 않는다(맵 원칙: 안전 관련은 분류 즉시 사람에게).
- 의도: 임베딩 제로샷(문의 ↔ 라벨 설명 유사도, 의미 응용의 분류와 같은 함수)이 기본. 라벨 붙인 문의가 쌓이면 학습 분류기로 바꿀 수 있고,
  두 방식의 정확도를 같은 문의 세트로 잰다(evaluate).
- 오류 코드: 문의 글의 'E4' · 'd80' 같은 표기를 뽑아 검색 질문에 붙인다(고객이 코드만 말하는 경우가 많다).
"""

import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from app.stages.apps import classify as apps_classify
from app.stages.apps import common as apps_common
from app.stages.embedding.model_manager import ModelSpec

PRESET = Path(__file__).parent / "presets" / "as_demo.json"
SAFETY = re.compile(r"감전|찌릿|전기가\s*(오|통)|불꽃|스파크|불이\s*(붙|나)|화재|연기|타는\s*냄새|탄\s*냄새|가스\s*냄새|폭발|누전")
# 전원과 증상 사이 거리는 15자까지 — 처음 6자로 두었더니 "전원 버튼을 눌러도 아무 반응이 없어요"(13자 사이)를 놓쳤다(라벨 문의 48개 실측)
HIGH = re.compile(r"누수|물이\s*(새|샙)|E9|HE|전원.{0,15}(안\s*켜|반응이?\s*없)|작동.{0,4}안\s*(돼|함)|급(해|합니다)")
CODE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,2}\d{1,2}|\d?[A-Za-z]{1,2}E|[A-Za-z]E)(?![A-Za-z0-9])")
KNOWN = {"E1", "E2", "E4", "E5", "E6", "E7", "E9", "IE", "OE", "UE", "DE", "LE", "D80", "TE", "HE"}


def preset() -> dict[str, Any]:
    return json.loads(PRESET.read_text(encoding="utf-8"))


def urgency(text: str) -> str:
    if SAFETY.search(text or ""):
        return "safety"
    return "high" if HIGH.search(text or "") else "normal"


def codes(text: str) -> list[str]:
    """문의 글의 오류 코드(알려진 표기만 — '5G' · 'A4' 같은 일반 낱말을 코드로 오해하지 않게)."""
    out = []
    for m in CODE.finditer(text or ""):
        c = m.group(1)
        if c.upper() in KNOWN and c not in out:
            out.append(c)
    return out


class Triage:
    """의도 제로샷 분류기 — 라벨 설명 벡터를 한 번만 만들어 둔다."""

    def __init__(self, spec: ModelSpec, intents: dict[str, str] | None = None) -> None:
        self.spec = spec
        self.intents = intents or preset()["intents"]
        self.labels = list(self.intents)
        self.label_vecs = apps_common.embed(spec, [f"{k}: {v}" for k, v in self.intents.items()], "document", task="classification")

    def intent(self, texts: list[str]) -> list[dict[str, Any]]:
        x = apps_common.embed(self.spec, texts, "query", task="classification")
        return apps_classify.zero_shot(x, self.label_vecs, self.labels)

    def __call__(self, text: str) -> dict[str, Any]:
        z = self.intent([text])[0]
        return {"intent": z["label"], "confidence": z["confidence"], "top": z["top"], "urgency": urgency(text), "codes": codes(text)}


def evaluate(spec: ModelSpec, inquiries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """같은 문의 세트로 의도(제로샷 vs 학습 분류기 5겹 교차검증) · 긴급도(규칙) 정확도."""
    inq = inquiries or preset()["inquiries"]
    texts = [q["text"] for q in inq]
    y = [q["intent"] for q in inq]
    tri = Triage(spec)
    zs = [z["label"] for z in tri.intent(texts)]
    zs_report = apps_classify.report(y, zs, tri.labels)
    x = apps_common.embed(spec, texts, "query", task="classification")
    cv, _cv_pred, cv_note = apps_classify.cross_validate(np.asarray(x), y, "logreg", 5)
    urg_true = [q["urgency"] for q in inq]
    urg_pred = [urgency(t) for t in texts]
    safety_true = [u == "safety" for u in urg_true]
    safety_pred = [u == "safety" for u in urg_pred]
    tp = sum(a and b for a, b in zip(safety_true, safety_pred, strict=True))
    code_true = [q.get("code") for q in inq if q.get("code")]
    code_hit = sum(1 for q in inq if q.get("code") and q["code"] in codes(q["text"]))
    return {
        "n": len(inq), "labels": tri.labels,
        "intent_zero_shot": {"accuracy": zs_report["accuracy"], "macro_f1": zs_report["macro_f1"], "per_class": zs_report["per_class"],
                             "errors": [{"text": t, "true": a, "pred": b} for t, a, b in zip(texts, y, zs, strict=True) if a != b][:20]},
        "intent_trained_cv": ({"method": "logreg"} | {k: cv[k] for k in ("accuracy", "macro_f1", "per_class", "folds")}) if cv else {"note": cv_note},
        "urgency": {"accuracy": round(sum(a == b for a, b in zip(urg_true, urg_pred, strict=True)) / len(inq), 3),
                    "safety_recall": round(tp / sum(safety_true), 3) if any(safety_true) else None,
                    "safety_precision": round(tp / sum(safety_pred), 3) if any(safety_pred) else None},
        "codes": {"n": len(code_true), "extracted": code_hit},
    }  # fmt: skip
