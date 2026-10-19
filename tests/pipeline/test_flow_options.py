"""연결 실행 옵션: 근거 압축 · 답변 방식(에이전트 · Best-of) · 비교 측정의 프롬프트 캐시 끄기."""

import json

import httpx

from app.core import llm
from app.core.config import get_settings
from tests.helpers import wait_job


def test_flow_compress_option(client, monkeypatch):

    import httpx

    from tests.helpers import DOCS

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
    assert wait_job(client, cs["job"])["status"] == "done"
    flow = {"config": {"mode": "bm25", "chunk_set_id": cs["id"]}, "answer": True, "context_top": 2}
    client.post("/api/flow/run", json={"question": "세탁기 배수 필터", "flow": flow})
    client.post("/api/flow/run", json={"question": "세탁기 배수 필터", "flow": flow | {"compress": {"keep": 2}}})
    plain, comp = seen[-2], seen[-1]
    assert len(comp) < len(plain) and "배수 필터를 청소하세요" in comp  # 읽을 글은 줄고 관련 문장은 남는다
    client.delete(f"/api/collections/{cid}")


def test_flow_answer_modes(client, rag_collection, scripted_llm):
    base = {"config": {"mode": "dense", "index_id": rag_collection["idx"]}, "answer": True, "context_top": 3}
    a = client.post("/api/flow/run", json={"question": "세탁기 배수", "flow": base | {"agent": {"max_steps": 4}}}).json()
    st = {s["key"]: s for s in a["steps"]}
    assert (
        st["model"]["status"] == "run"
        and "8a 에이전트" in st["model"]["detail"]
        and a["answer"]["agent_steps"]
        and "에이전트" in st["answer"]["detail"]
    )
    b = client.post("/api/flow/run", json={"question": "세탁기 배수", "flow": base | {"best_of": 3}}).json()
    assert "Best-of-3" in {s["key"]: s for s in b["steps"]}["model"]["detail"] and b["answer"]["best_of"]["picked"] == 0


def test_flow_comparison_disables_prompt_cache(client, rag_collection, scripted_llm):
    """연결 비교는 서버 프롬프트 캐시를 끄고 잰다 — 앞선 실행이 처리해 둔 경로만 빨라 보이지 않게(실측 #233)."""
    scripted_llm["cache"] = []
    flows = [{"label": "RAG", "config": {"mode": "dense", "index_id": rag_collection["idx"]}, "answer": True},
             {"label": "Best-of", "config": {"mode": "dense", "index_id": rag_collection["idx"]}, "answer": True, "best_of": 2}]  # fmt: skip
    done = wait_job(
        client, client.post("/api/flow/evaluate", json={"eval_set_id": rag_collection["set"], "flows": flows, "max_queries": None}).json()
    )
    assert done["status"] == "done", done.get("error")
    assert scripted_llm["cache"] and all(v is False for v in scripted_llm["cache"])
    # 사용자가 질문 하나를 실행할 때는 캐시를 그대로 쓴다(빠른 응답)
    scripted_llm["cache"] = []
    client.post("/api/flow/run", json={"question": "세탁기", "flow": flows[0]})
    assert scripted_llm["cache"] == [None]
