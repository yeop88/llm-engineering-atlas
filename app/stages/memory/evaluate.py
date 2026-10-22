"""ME7 여러 세션 평가: 몇 달에 걸친 상담 대화(정해진 씨앗) → 기억 · 갱신 · 과거 · 시간 · 없는 기억 질문 → 방식별 정답률 · 맥락 글자.

고객마다 세션 4개: ① 이름 · 주소 · 첫 제품 ② 선호 시간 · 첫 수리 ③ 이사 · 두 번째 제품 ④ 선호 바뀜 · 두 번째 수리. 세션마다 잡담을
섞어 '전체 기록 넣기'가 길어지게 한다(실제 상담 기록처럼). 질문 유형:
- 갱신: 지금 주소 · 지금 선호 시간(예전 값을 답하면 틀림)
- 과거: 처음 주소(무효가 된 이력이 남아 있어야 맞음)
- 누적: 보유 제품 전부
- 시간: 마지막 수리 날짜
- 없는 기억: 이메일 — 모른다고 해야 맞음(지어내면 틀림)
방식: full(전체 대화) · memory(핵심 + 관련 기억) · none(아무것도 없이 — 기준선). 채점은 정답 값이 답에 들어 있는가(목록은 모두), 없는 기억은
거절 표현이 있고 '@' 가 없는가. 정답 판정을 LLM 에 맡기지 않는다(판정 오류가 비교를 흐리지 않게).
"""

import random
from datetime import datetime
from typing import Any

PLACES = [
    "서울시 강남구",
    "서울시 마포구",
    "부산시 해운대구",
    "대구시 수성구",
    "인천시 연수구",
    "광주시 서구",
    "대전시 유성구",
    "수원시 영통구",
]
NAMES = ["김하나", "이두리", "박세나", "최다온", "정우진", "한지민", "오세린", "윤태호"]
PRODUCTS = ["WM-100", "WM-200", "DR-300", "DW-400", "WM-500"]
TIMES = ["오전", "오후", "저녁", "주말"]
REPAIRS = ["배수 펌프 수리", "히터 교체", "도어 잠금 장치 교체", "모터 점검"]
CHAT = ["오늘 날씨가 정말 덥네요.", "요즘 일이 바빠서 정신이 없어요.", "아이들이 방학이라 빨래가 많아요.", "주말에 가족 여행을 다녀왔어요.",
        "상담원분 친절하셔서 감사해요.", "전화 연결이 좀 오래 걸렸네요.", "다음 달에 이사 갈지도 고민 중이에요.", "TV 광고에서 새 모델을 봤어요."]  # fmt: skip
REFUSE = ("모르", "없습니다", "없어요", "알 수 없", "기록이 없", "정보가 없", "확인되지 않", "말씀하신 적")


def personas(n: int, seed: int = 7) -> list[dict[str, Any]]:
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        a1, a2 = rnd.sample(PLACES, 2)
        p1, p2 = rnd.sample(PRODUCTS, 2)
        t1, t2 = rnd.sample(TIMES, 2)
        r1, r2 = rnd.sample(REPAIRS, 2)
        d1 = (3, rnd.randint(5, 25))
        d2 = (8, rnd.randint(5, 25))
        name = NAMES[i % len(NAMES)]
        chat = lambda: " ".join(rnd.sample(CHAT, 3))  # noqa: E731
        sessions = [
            (datetime(2026, 3, 2, 10), f"안녕하세요. 저는 {name}이에요. {a1}에 살아요. {chat()} {p1} 세탁기를 써요. 문이 가끔 안 열려요."),
            (datetime(2026, 4, 10, 14), f"{chat()} {t1}에 방문해 주시면 좋아요. {d1[0]}월 {d1[1]}일에 {r1} 받았어요. {chat()}"),
            (datetime(2026, 6, 1, 11), f"{chat()} {a2}로 이사했어요. {p2} 도 샀어요. {chat()}"),
            (datetime(2026, 8, 15, 16), f"{chat()} 이제는 {t2}이 편해요. {d2[0]}월 {d2[1]}일에 {r2} 받았어요. {chat()}"),
        ]
        qs = [
            {"type": "갱신", "q": "이 고객의 지금 주소는 어디인가요?", "gold": [a2], "wrong": [a1]},
            {"type": "갱신", "q": "이 고객이 지금 선호하는 방문 시간대는?", "gold": [t2], "wrong": [t1]},
            {"type": "과거", "q": "이 고객이 처음 상담할 때 살던 곳은 어디였나요?", "gold": [a1]},
            {"type": "누적", "q": "이 고객이 가진 제품 모델을 모두 알려 주세요.", "gold": [p1, p2]},
            {"type": "시간", "q": "이 고객의 가장 최근 수리는 몇 월 며칠이었나요?", "gold": [f"{d2[0]}월 {d2[1]}일"]},
            {"type": "없는 기억", "q": "이 고객의 이메일 주소는 무엇인가요?", "gold": None},
        ]
        out.append({"owner": f"eval-{seed}-{i}", "name": name, "sessions": sessions, "questions": qs})
    return out


def grade(q: dict[str, Any], answer: str) -> bool:
    a = (answer or "").replace(" ", "")
    if q["gold"] is None:
        return any(w.replace(" ", "") in a for w in REFUSE) and "@" not in a
    ok = all(g.replace(" ", "") in a for g in q["gold"])
    if ok and q.get("wrong"):  # 예전 값만 말하거나 둘 다 '지금'이라고 하면 틀림 — 예전 값이 먼저 나오면 틀린 것으로
        first_wrong = min((a.find(w.replace(" ", "")) for w in q["wrong"] if w.replace(" ", "") in a), default=-1)
        first_gold = a.find(q["gold"][0].replace(" ", ""))
        ok = first_wrong < 0 or first_gold < first_wrong
    return ok


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in sorted({r["method"] for r in rows}):
        rs = [r for r in rows if r["method"] == m]
        types = sorted({r["type"] for r in rs})
        out[m] = {"n": len(rs), "acc": round(sum(r["correct"] for r in rs) / len(rs), 4), "context_chars": round(sum(r["chars"] for r in rs) / len(rs)),
                  "by_type": {t: round(sum(r["correct"] for r in rs if r["type"] == t) / sum(1 for r in rs if r["type"] == t), 4) for t in types}}  # fmt: skip
    return out
