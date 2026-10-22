"""TL2 학습 데이터 감사: 만든 뒤의 데이터를 다시 읽어 거르기에서 놓친 것을 센다.

후학습 데이터 만들기(P2)는 형식 · 질문 중복 · 평가 누수만 거른다. 하지만 학습을 망치는 것은 그 밖에도 있다.
- 같은 답 반복: 질문은 달라도 답이 같으면 모델이 그 답 하나를 외운다.
- 너무 짧은 답 · 거절 몫: 거절 예시가 너무 많으면 학습 뒤 정상 질문까지 거절한다(TL6 에서 보이는 증상의 원인).
- 채팅 틀 조각: '<|im_start|>' 같은 표시가 답에 남으면 모델이 그것을 글로 배운다.
- 선호 쌍의 길이 치우침: 고른 답이 늘 더 길면 DPO 가 '길게 쓰기'를 배운다.
고치지는 않는다. 건수와 예를 보여 주고, 다시 만들지는 사람이 정한다.
"""

import re
from typing import Any

from app.stages.flywheel.review import similar
from app.stages.posttrain import data as pt_data

REFUSAL = re.compile(r"찾을 수 없|찾지 못|확인되지 않|근거가 없|답변(을|드리기) 어렵|모르겠")
TEMPLATE = re.compile(r"<\|[a-z_]+\|>|<start_of_turn>|<end_of_turn>|\[INST\]|^\s*(assistant|user)\s*:", re.I | re.M)
SHORT, NEAR = 20, 0.8


def _answer(row: dict[str, Any]) -> str:
    msgs = row.get("messages") or []
    return next((m["content"] for m in reversed(msgs) if m.get("role") == "assistant"), "")


def _text(x: Any) -> str:
    if isinstance(x, list):  # 선호 쌍의 답이 메시지 목록일 때
        return next((m.get("content", "") for m in reversed(x) if m.get("role") == "assistant"), "")
    return str(x or "")


def _hangul(s: str) -> float:
    letters = [ch for ch in s if ch.isalpha()]
    return sum("가" <= ch <= "힣" for ch in letters) / len(letters) if letters else 0.0


def audit(name: str, max_rows: int = 2000) -> dict[str, Any]:
    rows = pt_data.load(name)[:max_rows]
    qs = [pt_data.question_of(r) for r in rows]
    out: dict[str, Any] = {"name": name, "n": len(rows), "kind": "dpo" if rows and rows[0].get("chosen") else "sft"}
    # 질문 거의 중복 — 만들 때의 거르기와 같은 기준(DUP)보다 조금 낮게 잡아 '비슷한 질문 무리'를 본다
    near = [(i, j) for i in range(len(qs)) for j in range(i + 1, len(qs)) if similar(qs[i], qs[j]) >= NEAR]
    out["near_dup_questions"] = {"pairs": len(near), "examples": [[qs[i][:60], qs[j][:60]] for i, j in near[:5]]}
    if out["kind"] == "sft":
        ans = [_answer(r) for r in rows]
        by: dict[str, list[int]] = {}
        for i, a in enumerate(ans):
            by.setdefault(re.sub(r"\s+", " ", a.strip()), []).append(i)
        rep = sorted(((k, v) for k, v in by.items() if len(v) > 1 and k), key=lambda kv: -len(kv[1]))
        lens = sorted(len(a) for a in ans)
        refusals = [i for i, a in enumerate(ans) if REFUSAL.search(a)]
        out |= {
            "same_answer": {
                "groups": len(rep),
                "rows": sum(len(v) for _, v in rep),
                "top": [{"answer": k[:80], "n": len(v)} for k, v in rep[:5]],
            },
            "answer_chars": {"min": lens[0], "median": lens[len(lens) // 2], "max": lens[-1]} if lens else None,
            "short": {"n": sum(n < SHORT for n in lens), "examples": [a[:60] for a in ans if len(a) < SHORT][:5]},
            "refusal_share": round(len(refusals) / max(1, len(ans)), 3),
            "template_leak": {"n": sum(bool(TEMPLATE.search(a)) for a in ans), "examples": [a[:80] for a in ans if TEMPLATE.search(a)][:3]},
            "hangul_share": round(sum(_hangul(a) for a in ans) / max(1, len(ans)), 3),
            "turns": round(sum(len(r.get("messages") or []) for r in rows) / max(1, len(rows)), 1),
        }
    else:
        ch, rj = [_text(r.get("chosen")) for r in rows], [_text(r.get("rejected")) for r in rows]
        longer = sum(len(a) > len(b) for a, b in zip(ch, rj, strict=True))
        out |= {
            "same_pair": sum(a.strip() == b.strip() for a, b in zip(ch, rj, strict=True)),
            # 고른 답이 더 긴 몫 — 0.5 근처가 좋다. 0.8 을 넘으면 DPO 가 내용보다 길이를 배울 수 있다
            "chosen_longer_share": round(longer / max(1, len(rows)), 3),
            "chosen_refusal_share": round(sum(bool(REFUSAL.search(a)) for a in ch) / max(1, len(ch)), 3),
            "template_leak": {"n": sum(bool(TEMPLATE.search(a + b)) for a, b in zip(ch, rj, strict=True))},
        }
    out["warnings"] = warnings(out)
    return out


def warnings(a: dict[str, Any]) -> list[str]:
    w = []
    n = max(1, a["n"])
    if a["near_dup_questions"]["pairs"] > n * 0.05:
        w.append(f"비슷한 질문 쌍 {a['near_dup_questions']['pairs']}개 — 같은 질문 무리가 학습을 치우치게 함")
    if a["kind"] == "sft":
        if a["same_answer"]["rows"] > n * 0.1:
            w.append(f"같은 답이 {a['same_answer']['rows']}행({a['same_answer']['groups']}종) — 그 답을 외움")
        if a["refusal_share"] > 0.3:
            w.append(f"거절 답이 {round(a['refusal_share'] * 100)}% — 학습 뒤 정상 질문도 거절할 수 있음")
        if a["short"]["n"] > n * 0.1:
            w.append(f"{SHORT}자 미만 답 {a['short']['n']}건")
    else:
        if a["same_pair"]:
            w.append(f"고른 답 = 버린 답 {a['same_pair']}쌍 — 배울 것이 없는 쌍")
        if a["chosen_longer_share"] > 0.8 or a["chosen_longer_share"] < 0.2:
            w.append(f"고른 답이 더 긴 몫 {a['chosen_longer_share']} — 길이 치우침")
    if a["template_leak"]["n"]:
        w.append(f"채팅 틀 조각이 든 답 {a['template_leak']['n']}건")
    return w
