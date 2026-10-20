"""G4 출력 정책 검사: 답변을 내보내기 전 마지막 관문 — 근거 · 질문 검증(2 RAG)에 분야별 금지 정책을 더한다.

정책은 분야(컬렉션 도메인)마다 다르다.
- 법률: 결과 단정('반드시 승소', '100% 처벌받지 않는다') — 근거를 인용해도 개별 사안의 결론은 단정할 수 없다 → 안내 문구를 덧붙여 수정
- 의료: 진단 · 처방 단정 → 안내 문구
- 고객 AS: 위험한 자가 조치(분해 · 전원을 켠 채 · 가스 부품) → 거절하고 방문 접수로, 보증 · 환불 약속 → 상담원 확인 문구
- 공통: 내부 비밀(키 · 비밀번호 형식), 개인정보(G2) → 가림

동작: pass(그대로) · fix(수정해 내보냄) · block(거절 문구로 바꿈). 무엇을 왜 바꿨는지 violations 로 남긴다(감사 · 평가용).
"""

import re
from typing import Any

from app.stages.guardrails import pii

Rule = tuple[str, str, re.Pattern[str]]  # (이름, 동작 fix|block, 정규식)

DOMAIN_RULES: dict[str, list[Rule]] = {
    "legal": [
        (
            "결과 단정",
            "fix",
            re.compile(
                r"(반드시|무조건|100\s?%|틀림없이|확실히)\s*[^.\n]{0,20}(승소|이깁|이길|이긴|처벌받지\s*않|무죄|패소하지\s*않|받을\s*수\s*있습니다)"
            ),
        ),
        ("결과 단정", "fix", re.compile(r"(승소|무죄|처벌을\s*피할\s*수)\s*[^.\n]{0,8}(확실|보장|틀림없)")),
    ],
    "medical": [
        ("진단 단정", "fix", re.compile(r"(확실히|틀림없이|분명히)\s*[^.\n]{0,15}(병|암|질환|증후군)입니다")),
        ("처방", "fix", re.compile(r"\d+\s?(mg|밀리그램|정|알)\s*(을|를)?\s*(복용|드세요|드십시오)")),
    ],
    "support": [
        (
            "위험한 자가 조치",
            "block",
            re.compile(r"(직접|스스로|혼자)\s*[^.\n]{0,15}(분해|뜯|열어|교체)[^.\n]{0,15}(하세요|하십시오|하면\s*됩니다|해\s*보세요)"),
        ),
        (
            "위험한 자가 조치",
            "block",
            re.compile(r"전원(을|이)?\s*(켠|연결한|꽂은)\s*(채|상태)(로|에서)\s*[^.\n]{0,20}(만지|분리|청소|열)"),
        ),
        (
            "위험한 자가 조치",
            "block",
            re.compile(r"(가스\s*(밸브|배관|호스)|고압\s*부품|콘덴서|축전기)\s*[^.\n]{0,15}(직접|스스로)?\s*(분리|교체|수리|만지)"),
        ),
        ("위험한 자가 조치", "block", re.compile(r"(젖은|물\s*묻은)\s*손으로\s*[^.\n]{0,10}(플러그|콘센트|전원)")),
        (
            "보증 · 환불 약속",
            "fix",
            re.compile(
                r"(무상|무료)\s*(으로\s*)?(수리|교체|교환)\s*(해\s*드립니다|됩니다|가능합니다)|환불\s*(해\s*드립니다|됩니다|받으실\s*수\s*있습니다)"
            ),
        ),
    ],
}
DOMAIN_RULES["as"] = DOMAIN_RULES["support"]
COMMON_RULES: list[Rule] = [
    (
        "내부 비밀",
        "fix",
        re.compile(r"\b(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|(?:password|비밀번호|passwd|api[_-]?key)\s*[:=]\s*\S{6,})", re.I),
    ),
]
NOTICE = {
    "결과 단정": "※ 위 내용은 근거 자료의 일반적인 설명이며, 구체적인 사안의 결과는 사실관계에 따라 달라질 수 있습니다. 변호사 등 전문가와 상담하세요.",
    "진단 단정": "※ 정확한 진단은 의료진의 진찰이 필요합니다.",
    "처방": "※ 약의 종류 · 용량은 의사 · 약사와 상담하세요.",
    "보증 · 환불 약속": "※ 무상 수리 · 환불 가능 여부는 보증 기간과 고장 원인을 상담원이 확인한 뒤 안내합니다.",
}
BLOCK_REPLY = {
    "위험한 자가 조치": "안전을 위해 직접 분해하거나 전원이 연결된 상태로 조치하는 방법은 안내하지 않습니다. 전원 플러그를 뽑고 방문 수리를 접수해 주세요.",
}


def domain_of(collection_domain: str | None) -> str:
    return {"legal": "legal", "support": "support", "product": "support", "medical": "medical"}.get(collection_domain or "", "general")


def check(answer: str, domain: str = "general", verify: dict[str, Any] | None = None) -> dict[str, Any]:
    """→ {"violations", "pii", "action": pass|fix|block, "fixed"(내보낼 글), "domain"}.
    verify(2 RAG 검증 결과)는 참고로 붙인다 — 근거 없음 · 관련 없음은 그 자체로 막지 않고(검증 화면이 표시) 기록만."""
    violations = []
    for name, act, rx in DOMAIN_RULES.get(domain, []) + COMMON_RULES:
        for m in rx.finditer(answer or ""):
            violations.append({"rule": name, "action": act, "match": m.group(0)[:80]})
    masked, hits = pii.mask(answer or "")
    action = "block" if any(v["action"] == "block" for v in violations) else ("fix" if violations or hits else "pass")
    fixed = answer or ""
    if action == "block":
        rule = next(v["rule"] for v in violations if v["action"] == "block")
        fixed = BLOCK_REPLY.get(rule, "정책에 맞지 않아 답하지 않았습니다. 상담원에게 연결합니다.")
    elif action == "fix":
        fixed = masked
        for v in violations:
            if v["rule"] == "내부 비밀":
                fixed = fixed.replace(v["match"], "[가림]")
        notes = list(dict.fromkeys(NOTICE[v["rule"]] for v in violations if v["rule"] in NOTICE))
        if notes:
            fixed = fixed.rstrip() + "\n\n" + "\n".join(notes)
    grounding = {}
    if verify:
        grounding = {
            k: verify.get(k) for k in ("supported_ratio", "relevant_ratio", "refused", "invalid_citations", "off_topic") if k in verify
        }
    return {"domain": domain, "violations": violations, "pii": pii.counts(hits), "action": action, "fixed": fixed, "grounding": grounding}
