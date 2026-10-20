"""문서 처리(D1~D7) 순수 함수: 메타데이터 정규화 · 파싱 점검 지표 · 표 마크다운 · PDF 표 추출 · 정제 · 판 묶음."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.db import Document
from app.stages.docintel import clean, layout, meta, parsing
from tests.stages.docintel.pdf import TABLE_PAGE, make_pdf


# ── D6 메타데이터 ──────────────────────────────────────────────────────
def test_normalize_lists_bools_and_text():
    # 목록 칸은 쉼표(전각 쉼표 포함)로 나누고 빈 값을 버린다 — 화면에서 한 칸에 여럿을 적으므로
    assert meta.normalize("acl", "hr， legal ,, ") == ["hr", "legal"]
    assert meta.normalize("product_model", ["WM-100", "", 200]) == ["WM-100", "200"]
    assert meta.normalize("product_model", None) == []
    assert meta.normalize("superseded", "on") is True and meta.normalize("superseded", "") is False
    assert meta.normalize("dept", "  인사팀 ") == "인사팀"
    assert meta.normalize("date", None) == ""


def test_update_sets_and_clears_fields():
    d = Document(meta={"source": "업로드", "dept": "옛 부서"})
    before = d.meta
    m = meta.update(d, {"doc_type": "규정", "dept": "", "acl": "hr, legal", "superseded": False})
    assert m == {"source": "업로드", "doc_type": "규정", "acl": ["hr", "legal"]}  # 빈 값은 칸을 지운다, 파서가 넣은 칸은 그대로
    assert d.meta is not before  # 새 dict 를 넣어야 JSON 칸 변경이 기록된다
    with pytest.raises(ValueError, match="고칠 수 없는 칸"):
        meta.update(d, {"original": "x"})


def test_matches_filters():
    m = {"doc_type": "규정", "dept": "인사", "product_model": ["WM-100"], "date": "2025-03-01"}
    assert meta._matches(m, {"doc_type": ["규정", "공지"]})
    assert not meta._matches(m, {"dept": ["재무"]})
    assert meta._matches(m, {"product_model": ["WM-100", "DR-300"]}) and not meta._matches(m, {"product_model": ["DR-300"]})
    assert meta._matches(m, {"date_from": "2025-01-01", "date_to": "2025-12-31"})
    assert not meta._matches(m, {"date_from": "2025-06-01"})
    assert not meta._matches({}, {"date_to": "2025-12-31"})  # 날짜가 없는 문서는 날짜 범위 필터에서 빠진다
    assert not meta._matches(m | {"superseded": True}, {"latest_only": True})
    assert not meta.active({"doc_type": [], "latest_only": False}) and meta.active({"latest_only": True})


# ── D2 파싱 점검 ───────────────────────────────────────────────────────
def test_broken_ratio():
    assert parsing.broken_ratio("") == 0.0
    assert parsing.broken_ratio("정상적인 한국어 문장입니다.") == 0.0
    assert parsing.broken_ratio("ab��") == 0.5  # 대체 문자 2 / 4
    assert parsing.broken_ratio("ㅎㅎㅎㅎ") == 1.0  # 자모만 이어진 것(인코딩이 깨진 흔적)
    assert parsing.broken_ratio("한글ㅎ") == 0.0  # 낱자 하나는 깨짐으로 보지 않는다


def test_char_accuracy():
    assert parsing.char_accuracy("공문서는 한글로", "공문서는  한글로") == 1.0  # 공백은 보지 않는다
    assert parsing.char_accuracy("", "") == 1.0 and parsing.char_accuracy("", "x") == 0.0
    acc = parsing.char_accuracy("배수 필터를 청소하세요", "배수 필터를 정소하세요")
    assert 0.85 < acc < 1.0


def test_report_flags_empty_pages():
    d = Document(id=1, filename="스캔.pdf", mime="application/pdf", n_chars=40, pages=["가" * 40, "", " 3 "],
                 meta={"page_kind": "page", "original": "ab/x.pdf"})  # fmt: skip
    r = parsing.report(d)
    assert r["empty_pages"] == [2, 3] and r["ocr_possible"] and r["has_original"]
    assert any("빈 쪽 2개" in i for i in r["issues"])
    all_empty = parsing.report(Document(id=2, filename="a.pdf", n_chars=0, pages=["", ""], meta={"page_kind": "page"}))
    assert any("OCR 이 필요" in i for i in all_empty["issues"]) and not all_empty["ocr_possible"]  # 원본이 없으면 OCR 불가


# ── D3 표 ──────────────────────────────────────────────────────────────
def test_table_markdown():
    md = layout.table_markdown([["분기", "매출"], ["1분기", "100"], [None, None], ["2분기", "2|00", "비고\n있음"]])
    assert md.splitlines() == ["| 분기 | 매출 |  |", "|---|---|---|", "| 1분기 | 100 |  |", "| 2분기 | 2/00 | 비고 있음 |"]
    assert layout.table_markdown([]) == "" and layout.table_markdown([[None, ""]]) == ""


def test_extract_tables_from_pdf():
    res = layout.extract(make_pdf([TABLE_PAGE]), figures=True)
    (page,) = res["pages"]
    assert page["tables"] and page["tables"][0][0] == ["Quarter", "Sales"]
    assert page["tables"][0][1:] == [["Q1", "100"], ["Q2", "200"]]
    # 표 안 글자는 본문에서 빠진다 — 표 글이 본문과 마크다운 표에 두 번 들어가지 않게
    assert "Sales report" in page["text"] and "Quarter" not in page["text"]
    assert page["figures"] == []


# ── D4 정제 · 중복 · 판 ───────────────────────────────────────────────
# 본문 줄은 쪽마다 모양이 달라야 한다(숫자만 다른 줄은 같은 모양 = 반복 줄로 본다)
BODIES = ["급여는 매월 25일에 지급한다.", "연차는 입사 1년 뒤 15일이다.", "출장 신청은 사흘 전에 한다.", "보안 교육은 해마다 받는다."]
PAGES = [f"사내 규정집 2025\n{b}\n- {i} -" for i, b in enumerate(BODIES, start=1)]


def test_boilerplate_and_clean_pages():
    rep = clean.boilerplate(PAGES)
    assert "사내 규정집 #" in rep  # 숫자 묶음 하나 = # 하나
    assert not clean.boilerplate(PAGES[:2])  # 2쪽 문서는 반복을 판단하지 않는다
    out, st = clean.clean_pages(PAGES)
    assert st["page_numbers"] == 4 and st["repeated_lines"] == 4
    assert out == BODIES


def test_apply_clean_skips_media_and_marks_changed():
    d = Document(pages=list(PAGES), meta={})
    st = clean.apply_clean(d)
    assert st["repeated_lines"] == 4 and d.meta["cleaned"]["page_numbers"] == 4 and d.meta.get("changed_at")
    m = Document(pages=["a"], meta={"media_items": [{"path": "x"}]})
    assert clean.apply_clean(m)["repeated_lines"] == 0 and "changed_at" not in m.meta


def _doc(i: int, filename: str, text: str, date: str | None = None, minutes: int = 0) -> Document:
    return Document(id=i, filename=filename, title=filename.rsplit(".", 1)[0], pages=[text],
                    meta={"date": date} if date else {}, created_at=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes))  # fmt: skip


def test_near_duplicates_and_version_groups():
    body = "공공기관등의 공문서는 어문규범에 맞추어 한글로 작성하여야 한다. 필요한 사항은 대통령령으로 정한다. " * 3
    docs = [
        _doc(1, "복무규정(2023.01).txt", body + "부칙 2023", date="2023-01-01"),
        _doc(2, "복무규정 개정 v2.txt", body + "부칙 2024", date="2024-05-01"),
        _doc(3, "출장비 지침.txt", "출장비는 실비로 정산한다. 숙박비 상한은 지역마다 다르다.", minutes=5),
        _doc(4, "출장비 지침_최종.txt", "완전히 다른 글이지만 제목만 판 표기가 다르다.", minutes=10),
    ]
    assert clean.base_title("복무규정(2023.01)") == clean.base_title("복무규정 개정 v2") == "복무규정"
    dups = clean.near_duplicates(docs, 0.8)
    assert [(p["a"], p["b"]) for p in dups] == [(1, 2)] and dups[0]["sim"] >= 0.8
    groups = {g["group"]: g for g in clean.version_groups(docs, dups)}
    assert groups["복무규정"]["latest"] == 2  # 문서 날짜가 늦은 것이 최신
    assert groups["출장비지침"]["latest"] == 4  # 날짜가 없으면 나중에 올린 것
    assert [m["superseded"] for m in groups["복무규정"]["members"]] == [False, True]
    assert clean.jaccard(set(), {1}) == 0.0


def test_version_groups_ignore_generic_titles():
    """회귀: 판례는 제목이 서식 공통 머리('【전문】【원고,피상고인】')라 제목으로 묶으면 다른 판례들이 한 문서의 판이 됐다."""
    generic = "【전문】【원고,피상고인】"
    body = "【전문】【원고,피상고인】 원고 【피고,상고인】 피고 【주문】 상고를 기각한다. 【이유】 상고이유를 판단한다. " * 4
    docs = [
        _doc(1, "근로기준법.txt", "제1조(목적) 이 법은 근로조건의 기준을 정한다."),
        _doc(2, "근로기준법 시행령.txt", "제1조(목적) 이 영은 근로기준법에서 위임된 사항을 정한다."),
        _doc(3, "판례 2021두35438 부당해고구제재심판정취소.txt", body + "2021두35438", minutes=1),
        _doc(4, "판례 2024다312566 임금.txt", body + "2024다312566", minutes=2),
        _doc(5, "판례 2002다23482 건물명도.txt", body + "2002다23482", minutes=3),
    ]
    for d in docs[2:]:
        d.title = generic
    dups = clean.near_duplicates(docs, 0.5)
    assert len(dups) == 3  # 서식이 같아 글이 많이 겹쳐도
    assert clean.version_groups(docs, dups) == []  # 판으로 묶지 않는다(사건번호 · 법령 이름이 다르면 다른 문서)


def test_version_groups_same_title_different_format():
    docs = [
        _doc(1, "2022년 국립국어원 업무계획.hwp", "업무계획 본문", minutes=0),
        _doc(2, "2022년 국립국어원 업무계획.pdf", "업무계획 본문 (PDF 판)", minutes=5),
        _doc(3, "2025 행정업무운영 편람(최종).hwpx", "편람"),
        _doc(4, "2025 행정업무운영 편람 수정본.hwpx", "편람 수정", minutes=9),
    ]
    docs[0].title = docs[1].title = "보도자료"  # 제목이 아니라 파일 이름이 기준
    groups = {g["group"]: g for g in clean.version_groups(docs)}
    assert set(groups) == {"2022년국립국어원업무계획", "2025행정업무운영편람"}
    assert groups["2022년국립국어원업무계획"]["latest"] == 2 and groups["2025행정업무운영편람"]["latest"] == 4
