"""OM4 멀티모달 턴 융합: 같은 순간의 말 · 화면 · 첨부를 한 질문으로, '이거' · '아까 그거' 같은 가리킴을 장면으로 푼다.

'이거 뭐예요?' 는 말만 보면 무엇을 묻는지 모르고, 화면만 보면 무엇이 궁금한지 모른다. 규칙은 단순하게 둔다:
- 지금을 가리키는 말(이거 · 이게 · 여기 · 지금 화면 · 이 표시)이 있으면 말한 시각의 장면(OM3 색인)을 붙인다.
- 지난 것을 가리키는 말(아까 · 전에 · 처음)이 있으면 색인에서 그 장면을 찾는다.
- 장면에 오류 코드가 있으면 질문에 코드를 넣는다 — 검색이 코드로 매뉴얼 항목을 찾는 것이 가장 정확했다(AS4).
- 가리킴이 없어도 첨부 사진이 있으면 그 사진은 근거와 함께 LLM 에 넘긴다(질문 글은 그대로).
가리킴을 장면 설명으로 바꾼 질문은 검색용이고, LLM 에는 원래 질문 + 장면 설명 + 그 프레임 사진이 함께 간다(바꿔 쓴 말이 틀려도 사진으로 바로잡게).
"""

import re
from typing import Any

from app.stages.omni import video

NOW = re.compile(r"이거|이게|이건|이것|요거|여기|지금 (?:화면|이거)|이 (?:표시|불|글자|버튼|화면|숫자|코드)|화면에 (?:보이는|뜬|나온)")
PAST = re.compile(r"아까|전에|방금 전|처음에|앞에서 (?:보여|비춘)")
POINTER_WORDS = re.compile(r"(?:이거|이게|이건|이것|요거|그거|그게|저거)")


def _scene_phrase(r: dict[str, Any]) -> str:
    parts = []
    if r.get("code"):
        parts.append(f"{r['code']} 표시")
    elif r.get("display"):
        parts.append(f"'{r['display'][:20]}' 표시")
    if r.get("caption"):
        parts.append(r["caption"][:60])
    return ", ".join(parts) or "화면"


def fuse(text: str, index: list[dict[str, Any]], now: float | None = None, attachments: int = 0,
         memory: dict[str, Any] | None = None, live: bool = False) -> dict[str, Any]:  # fmt: skip
    """→ {query(검색용), context(LLM 에 줄 장면 설명), scene(쓴 장면), pointer(now · past · implicit · None), codes, use_image}.
    live 는 지금 영상을 보고 있는 채널(영상 통화)에서 한 말인가 — 가리킴 없는 짧은 질문을 화면에 대한 것으로 볼지 정한다."""
    q = (text or "").strip()
    pointer = "past" if PAST.search(q) else ("now" if NOW.search(q) else None)
    scene = None
    if pointer == "past":
        scene = video.find(index, q, now)
    elif pointer == "now":
        scene = video.at(index, now)
    elif live and index and attachments == 0 and len(q) < 25 and re.search(r"뭐|왜|어떻게|무슨", q):
        # 가리킴은 없지만 짧은 질문을 영상 통화 중에 했다 — 지금 화면에 대한 질문일 가능성이 커 장면을 맥락으로만 붙인다(질문은 그대로)
        scene = video.at(index, now)
        pointer = "implicit"
    query = q
    codes: list[str] = []
    if scene is not None:
        phrase = _scene_phrase(scene)
        if pointer in ("now", "past"):
            query = POINTER_WORDS.sub(phrase, q, count=1) if POINTER_WORDS.search(q) else f"{phrase} — {q}"
        if scene.get("code"):
            codes.append(scene["code"])
            if scene["code"] not in query:
                query = f"{scene['code']} {query}"
    model = (memory or {}).get("product_model")
    if model and model not in query and (pointer or codes):
        query = f"{model} {query}"  # 앞 채널에서 말한 제품 — 코드는 제품마다 뜻이 달라 같이 넣는다
    context = ""
    if scene is not None:
        context = f"[영상 {scene['t']}초 장면] {_scene_phrase(scene)}" + (
            f" (보이는 것: {', '.join(scene['objects'][:5])})" if scene.get("objects") else ""
        )
    return {"query": query, "original": q, "context": context, "scene": scene, "pointer": pointer, "codes": codes,
            "use_image": scene is not None or attachments > 0, "changed": query != q}  # fmt: skip
