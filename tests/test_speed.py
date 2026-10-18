"""3순위(속도): 근거 압축 · 짧은 청크 합치기 · 연결 실행의 압축 옵션."""

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


def test_flow_compress_option(client, monkeypatch):
    import json

    import httpx

    from app.core import llm
    from app.core.config import get_settings
    from tests.test_rag import DOCS, _wait

    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "fake")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["messages"][-1]["content"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "배수 필터를 청소하세요 [1]."}}]})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    cid = client.post("/api/collections", json={"name": "압축"}).json()["id"]
    long_doc = "세탁기 배수가 안 될 때는 배수 필터를 청소하세요. " + " ".join(f"무관한 안내 문장 {i}번입니다." for i in range(30))
    client.post(
        f"/api/collections/{cid}/documents",
        files=[
            ("files", ("긴안내.txt", long_doc.encode(), "text/plain")),
            *[("files", (n, t.encode(), "text/plain")) for n, t in DOCS.items()],
        ],
    )
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 2000, "overlap": 0, "min_chars": 5}}
    ).json()
    assert _wait(client, cs["job"])["status"] == "done"
    flow = {"config": {"mode": "bm25", "chunk_set_id": cs["id"]}, "answer": True, "context_top": 2}
    client.post("/api/flow/run", json={"question": "세탁기 배수 필터", "flow": flow})
    client.post("/api/flow/run", json={"question": "세탁기 배수 필터", "flow": flow | {"compress": {"keep": 2}}})
    plain, comp = seen[-2], seen[-1]
    assert len(comp) < len(plain) and "배수 필터를 청소하세요" in comp  # 읽을 글은 줄고 관련 문장은 남는다
    client.delete(f"/api/collections/{cid}")
