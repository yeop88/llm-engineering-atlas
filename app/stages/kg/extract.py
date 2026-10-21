"""K3 데이터 추출: 법률 컬렉션 문서 → 온톨로지 노드 · 관계.

정형부터 — 법령 본문의 조문 머리('제23조(해고 등의 제한)'), 시행령의 '법 제N조', 판례의 【참조조문】 · 【참조판례】는 형식이 정해져
있어 LLM 없이 정확히 뽑힌다(맵 원칙: 정형 매핑을 먼저). 판례가 다루는 쟁점처럼 형식이 없는 것만 LLM 으로 뽑고(extract_issues),
온톨로지 검증(K2)과 쟁점 합치기(K4)를 거친다.
"""

import json
import re
from typing import Any

from app.core import llm
from app.core.db import Document
from app.stages.rag.legal import CASE_NO, norm_article

ART_HEAD = re.compile(r"^제\s?(\d{1,4})\s?조(?:\s?의\s?(\d{1,2}))?\s*(?:\(([^)]{1,60})\))?", re.MULTILINE)
PARENT_REF = re.compile(r"(?<![가-힣」])법\s?제\s?(\d{1,4})\s?조(?:\s?의\s?(\d{1,2}))?")
HEAD_LINE = re.compile(r"^(?P<title>.+?)\s*\((?P<court>[가-힣]+)\s+(?P<date>\d{8})\s+선고\s+(?P<case>[^)]+)\)")
SECTION = re.compile(r"【(?P<name>[^】]+)】(?P<body>.*?)(?=【|$)", re.S)
# 법령 이름 안의 띄어쓰기를 허용한다 — '여객자동차 운수사업법' · '상가건물 임대차보호법' · '노동조합 및 노동관계조정법'.
# 공용 인용 검사(rag/legal.py)의 정규식은 띄어쓰기 없는 이름만 잡아 '운수사업법' · '임대차보호법' · '시행령' 같은 조각이 법령이 됐다
# (그대로 두면 상가건물 임대차보호법이 '임대차보호법' 노드로 잘못 묶인다). 참조조문 칸은 형식이 정해져 있어 따로 읽는다.
CITED_LAW = re.compile(r"^(?:구\s*)?(?P<law>[가-힣ㆍ·][가-힣ㆍ·\s]*?(?:법률|법|령|규칙)(?:\s?(?:시행령|시행규칙))?)\s*(?=제\s?\d)")
BRACKET_REF = re.compile(r"「(?P<law>[^」]{2,60})」\s*제\s?(?P<num>\d{1,4})\s?조(?:\s?의\s?(?P<sub>\d{1,2}))?")
ART_ONLY = re.compile(r"제\s?(\d{1,4})\s?조(?:\s?의\s?(\d{1,2}))?")


def cited_articles(section: str) -> list[tuple[str, str]]:
    """【참조조문】 → [(법령, 조문)]. '[1] 근로기준법 제94조 제1항, 제95조 / [2] 구 근로기준법(2007. 4. 11. 법률 제8372호로 …) 제30조'.
    괄호(개정 연혁)를 지우고, 쉼표 · 빗금으로 나눈 조각에 법령 이름이 없으면 앞 조각의 법령을 이어 쓴다."""
    text = re.sub(r"\[\d+\]", " ", section)
    while re.search(r"\([^()]*\)", text):
        text = re.sub(r"\([^()]*\)", "", text)
    out: list[tuple[str, str]] = []
    law = ""
    # 쉼표 · 빗금으로만 나눈다 — '및' · 가운뎃점은 법령 이름 안에도 있다('노동조합 및 노동관계조정법', '일ㆍ가정 양립')
    for tok in re.split(r"[,/]", text):
        tok = tok.strip()
        if not tok:
            continue
        if m := CITED_LAW.match(tok):
            law = law_name(m.group("law"))
        if not law:
            continue
        for a in ART_ONLY.finditer(tok):  # '제3조 및 제4조' 처럼 한 조각에 여럿
            pair = (law, norm_article(a.group(1), a.group(2)))
            if pair not in out:
                out.append(pair)
    return out


def law_name(name: str) -> str:
    """'근로기준법시행령' · '근로기준법 시행령' → '근로기준법 시행령' (띄어쓰기 통일 — 같은 법령이 두 노드가 되지 않게).
    가운뎃점도 통일('일·가정' · '일ㆍ가정' → 'ㆍ', 법령 공식 표기) — 판례마다 달리 적혀 같은 법률이 둘로 나뉘었다."""
    name = re.sub(r"\s+", " ", name.strip()).replace("·", "ㆍ")
    return re.sub(r"(?<=[가-힣])\s?(시행령|시행규칙)$", r" \1", name)


def article_key(law: str, num: str, sub: str | None = None) -> str:
    return f"{law_name(law)} {norm_article(num, sub)}"


def _sections(text: str) -> dict[str, str]:
    return {m.group("name").strip(): m.group("body").strip() for m in SECTION.finditer(text)}


def statute(doc: Document) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """법령 문서 → 법령 · 조문 노드, 조문 -속함-> 법령, 시행령 조문 -참조-> 법률 조문."""
    law = law_name(re.sub(r"\.(txt|md)$", "", doc.filename))
    is_decree = law.endswith(("시행령", "시행규칙"))
    parent = law.rsplit(" ", 1)[0] if is_decree else None
    nodes = [
        {
            "label": "Statute",
            "key": law,
            "name": law,
            "props": {"kind": "시행령" if is_decree else "법률", "external": False},
            "document_id": doc.id,
        }
    ]
    edges: list[dict[str, Any]] = []
    text = "\n".join(doc.pages or [])
    heads = list(ART_HEAD.finditer(text))
    for i, m in enumerate(heads):
        key = article_key(law, m.group(1), m.group(2))
        body = text[m.start() : heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        title = m.group(3) or ""
        nodes.append({"label": "Article", "key": key, "name": f"{key}({title})" if title else key, "document_id": doc.id,
                      "props": {"law": law, "no": norm_article(m.group(1), m.group(2)), "title": title, "chars": len(body), "external": False}})  # fmt: skip
        edges.append({"src": ("Article", key), "dst": ("Statute", law), "type": "PART_OF"})
        if parent:  # 시행령의 '법 제N조' = 모법 조문
            for r in PARENT_REF.finditer(body):
                edges.append(
                    {"src": ("Article", key), "dst": ("Article", article_key(parent, r.group(1), r.group(2))), "type": "REFERS_TO"}
                )
        for r in BRACKET_REF.finditer(body):  # '「근로기준법」 제2조' 처럼 다른 법령을 이름으로 가리킨 것(낫표가 이름 경계라 정확)
            other = law_name(r.group("law"))
            if other != law:
                edges.append(
                    {"src": ("Article", key), "dst": ("Article", article_key(other, r.group("num"), r.group("sub"))), "type": "REFERS_TO"}
                )
    return nodes, edges


def precedent(doc: Document) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """판례 문서 → 판례 노드, 【참조조문】 → 인용, 【참조판례】 → 판례 인용. 셋째 값은 쟁점 추출에 쓸 판시사항."""
    text = "\n".join(doc.pages or [])
    first = text.splitlines()[0] if text else ""
    src = (doc.meta or {}).get("source") or {}
    m = HEAD_LINE.match(first)
    case = src.get("case_no") or (m.group("case").split(",")[0].strip() if m else "")
    if not case:
        return [], [], {}
    date = m.group("date") if m else ""
    props = {"case_no": case, "external": False, "title": m.group("title").strip() if m else "", "court": m.group("court") if m else "",
             "date": f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else ""}  # fmt: skip
    nodes = [
        {
            "label": "Precedent",
            "key": case,
            "name": f"{props['title']} ({case})" if props["title"] else case,
            "props": props,
            "document_id": doc.id,
        }
    ]
    edges: list[dict[str, Any]] = []
    sec = _sections(text)
    for law, art in cited_articles(sec.get("참조조문", "")):
        edges.append({"src": ("Precedent", case), "dst": ("Article", f"{law} {art}"), "type": "CITES"})
    for mm in CASE_NO.finditer(sec.get("참조판례", "")):
        other = f"{mm.group(1)}{mm.group(2)}{mm.group(3)}"
        if other != case:
            edges.append({"src": ("Precedent", case), "dst": ("Precedent", other), "type": "CITES_CASE"})
    return nodes, edges, {"case_no": case, "holding": sec.get("판시사항", "")[:1500]}


def external_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """자료에 본문이 없지만 인용된 조문 · 판례 · 법령도 노드로 둔다(external) — '민법 제750조를 인용한 판례' 같은 질문에 답하려면 필요."""
    have = {(n["label"], n["key"]) for n in nodes}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for e in edges:
        for lb, key in (e["src"], e["dst"]):
            if (lb, key) in have or (lb, key) in out:
                continue
            if lb == "Article":
                law, no = key.rsplit(" ", 1)
                out[(lb, key)] = {"label": "Article", "key": key, "name": key, "props": {"law": law, "no": no, "external": True}}
                if ("Statute", law) not in have and ("Statute", law) not in out:
                    out[("Statute", law)] = {
                        "label": "Statute",
                        "key": law,
                        "name": law,
                        "props": {"kind": "시행령" if law.endswith("시행령") else "법률", "external": True},
                    }
            elif lb == "Precedent":
                out[(lb, key)] = {"label": "Precedent", "key": key, "name": key, "props": {"case_no": key, "external": True}}
    extra = list(out.values())
    for n in extra:  # 바깥 조문도 법령에 붙인다
        if n["label"] == "Article":
            edges.append({"src": ("Article", n["key"]), "dst": ("Statute", n["props"]["law"]), "type": "PART_OF"})
    return extra


ISSUE_SYSTEM = (
    "당신은 판례의 판시사항에서 법적 쟁점을 뽑는 도구입니다. 쟁점은 2~8 단어의 짧은 명사구(예: '취업규칙 불이익 변경', '통상임금 해당 여부', "
    '\'소액임차인 최우선변제\')로, 1~3개만 뽑습니다. 사건의 당사자 · 사실관계가 아니라 일반적인 법적 문제를 적습니다. JSON 만 출력합니다: {"issues": ["…"]}'
)


def extract_issues(lcfg: llm.LLMConfig, holding: str) -> list[str]:
    """판시사항 → 쟁점 1~3개. 형식이 어긋나면 빈 목록(그 판례는 쟁점 없이 — 지어낸 쟁점보다 낫다)."""
    if not holding.strip():
        return []
    try:
        data, _ = llm.chat_json(lcfg, ISSUE_SYSTEM, f"판시사항:\n{holding}", max_tokens=200, temperature=0.0)
    except llm.LLMError, ValueError, json.JSONDecodeError:
        return []
    items = data.get("issues") if isinstance(data, dict) else None
    out = []
    for x in items or []:
        s = re.sub(r"\s+", " ", str(x)).strip(" .·-")
        if 2 <= len(s) <= 40 and s not in out:
            out.append(s)
    return out[:3]
