"""국가법령정보 공동활용 API(law.go.kr DRF)로 법령 원문 · 시행일별 판(版)을 받는다 (규제 대응 RC1 · RC7).

왜 데이터셋이 아니라 API 인가: 법률 데이터셋(smhilee/korean-law-dataset)은 조문 가지번호('제37조의2')를 버려 제37조와 제37조의2 가
한 번호로 섞이고, 판이 하나(개인정보 보호법은 2023-09-15 시행판)뿐이다. 규제 대응은 '어느 판의 어느 조항'이 핵심이라
— 개정 전후 조항이 섞이면 잘못된 통제로 이어진다(맵 원칙) — 시행일별 판을 받을 수 있는 API 를 쓴다. 인공지능 기본법(2026-01 시행)은
데이터셋에 아예 없다.

키(OC)는 open.law.go.kr 에서 신청한 이메일 아이디다(설정 LAW_API_OC). 법령 원문은 저작권법 제7조의 비보호 저작물이다.
"""

import re
from typing import Any

import httpx

from app.core.config import get_settings

BASE = "https://www.law.go.kr/DRF"
LICENSE = "공공누리 제1유형 · 저작권법 제7조 비보호 저작물 (출처: 국가법령정보센터 공동활용 API)"


class LawApiError(RuntimeError):
    pass


def _oc() -> str:
    oc = get_settings().law_api_oc
    if not oc:
        raise LawApiError("LAW_API_OC 가 설정되지 않았습니다 (.env) — open.law.go.kr 에서 공동활용 신청 후 이메일 아이디")
    return oc


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        r = httpx.get(f"{BASE}/{path}", params={"OC": _oc(), "type": "JSON"} | params, timeout=60)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LawApiError(f"국가법령정보 API 오류: {exc}") from exc


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else [v] if v else []


def versions(name: str) -> list[dict[str, Any]]:
    """법령 이름 → 시행일별 판 [{mst, enforced, promulgated, status(현행 · 연혁 · 시행예정), kind}], 시행일 최신순. 이름이 정확히 같은 것만."""
    data = _get("lawSearch.do", {"target": "eflaw", "query": name, "display": 100})
    out = []
    for x in _as_list(data.get("LawSearch", {}).get("law")):
        if x.get("법령명한글") == name:
            out.append({"mst": x["법령일련번호"], "enforced": x["시행일자"], "promulgated": x["공포일자"], "status": x["현행연혁코드"],
                        "kind": x.get("제개정구분명", "")})  # fmt: skip
    return sorted(out, key=lambda v: v["enforced"], reverse=True)


def version_on(name: str, date: str | None = None) -> dict[str, Any]:
    """그 날짜(YYYYMMDD)에 시행 중이던 판. 날짜가 없으면 현행."""
    vs = versions(name)
    if not vs:
        raise LawApiError(f"법령을 찾지 못했습니다: {name}")
    if date is None:
        cur = [v for v in vs if v["status"] == "현행"]
        return cur[0] if cur else vs[0]
    past = [v for v in vs if v["enforced"] <= date]
    if not past:
        raise LawApiError(f"{name}: {date} 에 시행 중인 판이 없습니다")
    return past[0]


def fetch(mst: str, enforced: str) -> dict[str, Any]:
    """한 판의 원문 → {law, enforced, promulgated, mst, articles: [{no, title, text}]}. no 는 '제37조의2'."""
    data = _get("lawService.do", {"target": "eflaw", "MST": mst, "efYd": enforced})
    law = data.get("법령") or {}
    info = law.get("기본정보") or {}
    if not info:
        raise LawApiError(f"법령 원문이 비었습니다 (MST {mst}, 시행 {enforced})")
    arts = []
    for a in _as_list((law.get("조문") or {}).get("조문단위")):
        if a.get("조문여부") != "조문":  # '전문' = 장 · 절 제목
            continue
        no = f"제{a['조문번호']}조" + (f"의{a['조문가지번호']}" if a.get("조문가지번호") else "")
        arts.append({"no": no, "title": a.get("조문제목") or "", "text": _article_text(a)})
    return {"law": info.get("법령명_한글", ""), "enforced": info.get("시행일자", enforced), "promulgated": info.get("공포일자", ""),
            "mst": mst, "articles": arts}  # fmt: skip


def _article_text(a: dict[str, Any]) -> str:
    """조문 → '제N조(제목) 본문' 첫 줄 + 항 · 호 · 목을 한 줄씩. 공개 자료 가져오기(public_corpus._law_text)와 같은 모양이라
    법령 청킹 · 조문 번호 조회가 그대로 동작한다."""
    lines = [re.sub(r"\s+", " ", str(a.get("조문내용") or "")).strip()]
    for h in _as_list(a.get("항")):
        if txt := str(h.get("항내용") or "").strip():
            lines.append(re.sub(r"\s+", " ", txt))
        for ho in _as_list(h.get("호")):
            if txt := str(ho.get("호내용") or "").strip():
                lines.append(re.sub(r"\s+", " ", txt))
            for mok in _as_list(ho.get("목")):
                for t in _as_list(mok.get("목내용")):
                    if txt := str(t).strip():
                        lines.append(re.sub(r"\s+", " ", txt))
    return "\n".join(x for x in lines if x)


def document(v: dict[str, Any]) -> dict[str, Any]:
    """fetch 결과 → 컬렉션에 넣을 문서(파일 이름 · 본문 · 출처). 판 정보(시행일 · MST)를 출처에 남겨 개정 감시가 비교한다."""
    text = f"{v['law']}\n시행 {v['enforced']} · 공포 {v['promulgated']}\n\n" + "\n".join(a["text"] for a in v["articles"])
    return {"filename": f"{v['law']}.txt", "text": text,
            "source": {"kind": "statute", "law": v["law"], "api": "law.go.kr", "mst": v["mst"], "enforced": v["enforced"],
                       "promulgated": v["promulgated"], "articles": len(v["articles"]), "license": LICENSE}}  # fmt: skip
