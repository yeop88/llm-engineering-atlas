"""RAG 답변 생성: 근거 구성 · 인용 파싱 · 글자 기반 검증 · 스트리밍(가짜 LLM)."""

import json

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.stages.rag import answer
from tests.helpers import DOCS, wait_job

SOURCES = [
    {
        "filename": "보도자료.txt",
        "page": None,
        "heading": "",
        "text": "등록 대상임에도 등록을 하지 않은 경우 2천만 원 이하의 벌금이 부과될 수 있습니다.",
    },
    {"filename": "법령.txt", "page": 3, "heading": "제14조", "text": "공공기관등의 공문서는 어문규범에 맞추어 한글로 작성하여야 한다."},
]


def test_context_and_citations():
    ctx, used = answer.build_context(SOURCES, max_chars=10_000)
    assert ctx.startswith("[1] (보도자료.txt)") and "[2] (법령.txt p.3 · 제14조)" in ctx and len(used) == 2
    _, used = answer.build_context(SOURCES, max_chars=60)
    assert len(used) == 1  # 한도를 넘으면 뒤 근거는 뺀다 (첫 근거는 항상)
    assert answer.citations("벌금입니다 [1]. 한글로 씁니다 [2, 1][3]") == [1, 2, 3]


def test_verify_lexical_flags_unsupported_and_bad_citations():
    text = "등록하지 않으면 2천만 원 이하의 벌금이 부과될 수 있습니다 [1]. 공문서는 영어로 작성해야 합니다 [2]. 과태료는 5억 원입니다 [7]. 참고하세요."
    v = answer.verify_lexical(text, SOURCES)
    st = [s["status"] for s in v["sentences"]]
    assert st[0] == "supported" and st[1] in ("weak", "unsupported") and st[2] == "unsupported" and st[3] == "uncited"
    assert v["invalid_citations"] == [7] and v["cited_sources"] == [1, 2] and v["supported_ratio"] == 0.25
    r = answer.verify_lexical(f"{answer.NOT_FOUND}.", SOURCES)
    assert r["refused"] and r["sentences"][0]["status"] == "refusal" and r["supported_ratio"] is None


def test_think_filter_across_chunks():
    f = llm._ThinkFilter()
    out = "".join(f.feed(p) for p in ["안녕 <thi", "nk>속생각", "</th", "ink>\n답", "입니다 <", "b>"]) + f.flush()
    assert out == "안녕 답입니다 <b>"


def _sse(events: list[dict]) -> bytes:
    return "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events).encode() + b"data: [DONE]\n\n"


@pytest.fixture
def fake_llm(monkeypatch):
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "fake")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if body.get("stream"):
            pieces = ["해외직구 구매대행", "업체 등록제는 7월 1일부터 ", "시행됩니다 [1]."]
            ev = [{"choices": [{"delta": {"content": p}}]} for p in pieces]
            ev.append({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 50, "completion_tokens": 12}})
            return httpx.Response(200, content=_sse(ev), headers={"content-type": "text/event-stream"})
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"judgements": [{"n": 1, "supported": true, "reason": "근거 1"}]}'}}]}
        )

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    return seen


def test_answer_stream_api(client, fake_llm):
    cid = client.post("/api/collections", json={"name": "답변 테스트"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in DOCS.items()])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert wait_job(client, cs["job"])["status"] == "done"
    body = {
        "question": "해외직구 구매대행업체 등록제 시행",
        "config": {"mode": "bm25", "chunk_set_id": cs["id"]},
        "context_top": 3,
        "judge": True,
    }
    with client.stream("POST", f"/api/collections/{cid}/answer", json=body) as r:
        assert r.status_code == 200
        events = [json.loads(line) for line in r.iter_lines() if line.strip()]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "search" and kinds.count("delta") == 3 and kinds[-3:] == ["verify", "judge", "done"]
    assert events[0]["sources"][0]["filename"] == "보도자료.txt" and len(events[0]["sources"]) <= 3
    done = events[-1]
    assert done["answer"].endswith("[1].") and done["usage"]["output_tokens"] == 12 and done["run_id"]
    verify = next(e for e in events if e["type"] == "verify")
    assert verify["cited_sources"] == [1] and verify["sentences"][0]["status"] == "supported"
    assert next(e for e in events if e["type"] == "judge")["supported_ratio"] == 1.0
    stream_req = next(b for b in fake_llm if b.get("stream"))
    assert stream_req["chat_template_kwargs"] == {"enable_thinking": False} and "근거:" in stream_req["messages"][1]["content"]
    # 잘못된 설정 → 오류 이벤트, LLM 미설정 → 400
    with client.stream("POST", f"/api/collections/{cid}/answer", json=body | {"config": {"mode": "dense", "index_id": 999999}}) as r:
        assert json.loads(next(r.iter_lines()))["type"] == "error"
    get_settings().openai_model = None
    assert client.post(f"/api/collections/{cid}/answer", json=body).status_code == 400
    client.delete(f"/api/collections/{cid}")


def test_anthropic_stream(monkeypatch):
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 9}}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "안녕"}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "하세요"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}},
    ]
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events).encode()
    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(lambda req: httpx.Response(200, content=body)))
    out = list(llm.chat_stream(llm.LLMConfig("anthropic", "m", llm.ANTHROPIC_URL, "k"), "s", "u"))
    assert (
        [o["delta"] for o in out[:-1]] == ["안녕", "하세요"]
        and out[-1]["text"] == "안녕하세요"
        and out[-1]["usage"] == {"input_tokens": 9, "output_tokens": 3}
    )


def test_answer_eval_job(client, fake_llm):
    cid = client.post("/api/collections", json={"name": "답변 평가 테스트"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in DOCS.items()])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert wait_job(client, cs["job"])["status"] == "done"
    docs = {d["filename"]: d["id"] for d in client.get(f"/api/collections/{cid}").json()["documents"]}
    s = client.post(
        f"/api/collections/{cid}/eval-sets",
        json={"name": "e", "items": [
            {"query": "해외직구 구매대행업체 등록제 시행", "doc_ids": [docs["보도자료.txt"]], "evidence": "구매대행업체 등록제를 시행한다"},
            {"query": "공문서는 무엇으로 작성", "doc_ids": [docs["법령.txt"]], "evidence": "공문서는 어문규범에 맞추어 한글로 작성하여야 한다"},
        ]},
    ).json()  # fmt: skip
    job = client.post(
        f"/api/eval-sets/{s['id']}/answer-eval", json={"config": {"mode": "bm25", "chunk_set_id": cs["id"]}, "context_top": 3}
    ).json()
    job = wait_job(client, job)
    assert job["status"] == "done", job
    r = job["result"]
    assert r["summary"]["n"] == 2 and r["summary"]["answer_rate"] == 1.0 and len(r["rows"]) == 2 and r["run_id"]
    assert all(row["evidence_retrieved"] is not None for row in r["rows"])
    client.delete(f"/api/collections/{cid}")
