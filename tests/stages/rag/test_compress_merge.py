"""속도: 근거 압축 · 짧은 청크 합치기."""

from app.stages.rag import answer, chunking


def test_compress_keeps_relevant_sentences_in_order():
    text = ("회사는 직원 복지를 위해 노력한다. 사용자는 정당한 이유 없이 근로자를 해고하지 못한다. 식당은 12시에 연다. "
            "해고는 서면으로 통지하여야 효력이 있다. 주차장은 지하에 있다. 사내 동호회는 자유롭게 만든다.")  # fmt: skip
    out = answer.compress([{"text": text, "filename": "a"}], "정당한 이유 없는 해고와 서면 통지", keep=2, min_chars=0)[0]
    assert "해고하지 못한다" in out["text"] and "서면으로 통지" in out["text"] and "식당" not in out["text"]
    assert out["text"].index("해고하지") < out["text"].index("서면으로") and "…" in out["text"]  # 원래 순서, 빠진 곳 표시
    assert out["compressed_from"] == len(text)
    short = {"text": "짧은 근거입니다.", "filename": "b"}
    assert answer.compress([short], "근거", keep=1)[0] is short  # 짧은 청크는 그대로


def test_merge_short_chunks():
    page = (
        "\n".join(f"제{i}조(조문{i}) 사용자는 짧은 의무 {i}번을 지킨다." for i in range(1, 9))
        + "\n제9조(긴 조문) "
        + "긴 내용입니다. " * 40
    )
    base = chunking.chunk_pages([page], {"method": "legal", "size": 400, "overlap": 0}, paged=False)
    merged = chunking.chunk_pages([page], {"method": "legal", "size": 400, "overlap": 0, "merge_below": 120}, paged=False)
    assert len(base) == 9 and len(merged) < len(base)  # 짧은 조문 8개가 합쳐진다
    assert all(len(c.text) >= 120 for c in merged[:-1])
    first = merged[0]
    assert first.text.startswith("제1조") and first.text.count("제2조") == 1  # 원문 구간으로 다시 잘라 중복 없음
    assert first.meta["heading"].endswith(" 외") and " 외 외" not in first.meta["heading"]
    assert all(len(c.text) <= 400 for c in merged)
    assert chunking.normalize({"merge_below": 99999, "size": 800})["merge_below"] == 800
