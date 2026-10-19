"""1순위(평가 자료): 공개 자료 가져오기 · 어려운 질문 유형(여러 문서 · 조건 · 긴 상황 · 답 없음) 생성과 채점 규칙."""

import json

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.stages.rag import answer, evaluation, public_corpus
from app.stages.rl import reward
from tests.helpers import wait_job

LAW = "제23조(해고 등의 제한) ① 사용자는 근로자에게 정당한 이유 없이 해고하지 못한다."


CASE = "【판결요지】 정당한 이유 없이 한 해고는 무효이고 사용자는 해고 기간의 임금을 지급하여야 한다. 【참조조문】 근로기준법 제23조"


def test_judge_requires_all_evidences():
    item = {"doc_ids": [1, 2], "evidences": [LAW, CASE]}
    res = [{"document_id": 1, "text": LAW}, {"document_id": 3, "text": "무관"}, {"document_id": 2, "text": CASE}]
    j = evaluation.judge(res, item, evaluation.evidence_grams(item))
    assert j["rank"] == 3  # 두 번째 근거가 나온 순위 — 하나만 찾으면 답할 수 없다
    assert evaluation.judge(res[:2], item, evaluation.evidence_grams(item))["rank"] is None
    # 근거 문장 없이 문서만 아는 여러 문서 질문: 정답 문서들이 모두 나온 순위
    assert evaluation.judge(res, {"doc_ids": [1, 2]}, None)["rank"] == 3


def test_evidence_in_sources_and_quality():
    item = {"doc_ids": [1, 2], "evidences": [LAW, CASE]}
    srcs = [{"text": LAW}, {"text": CASE}]
    both = evaluation.evidence_in_sources(srcs, item, [1, 2])
    one = evaluation.evidence_in_sources(srcs, item, [1])
    assert both["evidence_cited"] and not one["evidence_cited"] and one["evidence_cited_any"] and one["evidence_retrieved"]
    assert evaluation.answer_quality(both, item) == 1.0 and evaluation.answer_quality(one, item) == 0.0
    una = {"doc_ids": [], "answerable": False}
    assert not evaluation.answerable(una) and evaluation.answer_quality({"refused": True}, una) == 1.0
    assert evaluation.answer_quality({"refused": False}, una) == 0.0  # 답 없는 질문에 답하면 0점(지어냄)


def test_summarize_counts_refusals_separately():
    rows = [
        {
            "refused": False,
            "supported_ratio": 1.0,
            "invalid_citations": [],
            "evidence_cited": True,
            "evidence_retrieved": True,
            "seconds": 1,
            "quality": 1.0,
        },
        {"refused": True, "supported_ratio": None, "invalid_citations": [], "answerable": False, "seconds": 1, "quality": 1.0},
        {"refused": False, "supported_ratio": 0.5, "invalid_citations": [], "answerable": False, "seconds": 1, "quality": 0.0},
    ]
    s = answer.summarize_eval(rows)
    assert (
        s["n"] == 3
        and s["n_unanswerable"] == 2
        and s["correct_refusal"] == 0.5
        and s["answer_rate"] == 1.0
        and s["quality"] == round(2 / 3, 3)
    )


def test_reward_on_unanswerable():
    una = {"doc_ids": [], "answerable": False}
    assert reward.reward("근거에서 찾을 수 없습니다.", [{"text": "x"}], item=una)["parts"] == {"honest_refusal": 0.5}
    assert reward.reward("월 300만 원입니다 [1].", [{"text": "x"}], item=una)["parts"] == {"hallucination": -1.0}


def test_run_eval_skips_unanswerable():
    items = [{"id": "q1", "query": "a", "doc_ids": [1], "evidence": LAW}, {"id": "q2", "query": "b", "doc_ids": [], "answerable": False}]
    res = evaluation.run_eval(
        lambda q, c: {"results": [{"document_id": 1, "text": LAW, "filename": "f"}], "total_ms": 1.0}, items, [{"label": "x"}]
    )
    assert res["n_queries"] == 1 and res["n_unanswerable_skipped"] == 1 and res["results"][0]["metrics"]["hit@1"] == 1.0


def test_related_pairs_link_different_documents():
    ps = [{"chunk_id": 1, "document_id": 1, "text": LAW}, {"chunk_id": 2, "document_id": 2, "text": CASE},
          {"chunk_id": 3, "document_id": 1, "text": "제50조(근로시간) 1주 간의 근로시간은 40시간을 초과할 수 없다."},
          {"chunk_id": 4, "document_id": 3, "text": "보증금은 임대차 종료 후 돌려받는다."}]  # fmt: skip
    pairs = evaluation.related_pairs(ps, 5, min_overlap=0.05)
    assert pairs and all(a["document_id"] != b["document_id"] for a, b in pairs)
    assert {pairs[0][0]["chunk_id"], pairs[0][1]["chunk_id"]} == {1, 2}  # 조문과 그 조문을 인용한 판례가 짝


def test_law_text_dedups_repeated_heads():
    rows = [{"조문내용": "제2조(정의)", "항내용": "① 뜻은 다음과 같다.", "호내용": f"{i}. 항목{i}"} for i in (1, 2, 3)]
    rows.append({"조문내용": "제2조(정의)", "항내용": "② 평균임금은 통상임금보다 적으면 안 된다.", "호내용": None})
    t = public_corpus._law_text(rows)
    assert t.count("제2조(정의)") == 1 and t.count("① 뜻은") == 1 and "3. 항목3" in t and "②" in t


def test_eval_item_schema(client):
    cid = client.post("/api/collections", json={"name": "스키마"}).json()["id"]
    bad = client.post(f"/api/collections/{cid}/eval-sets", json={"name": "x", "items": [{"query": "q", "doc_ids": []}]})
    assert bad.status_code == 422  # 답이 있는 질문은 정답 문서가 필요
    ok = client.post(f"/api/collections/{cid}/eval-sets", json={"name": "x", "items": [{"query": "q", "answerable": False}]})
    assert ok.status_code in (200, 201), ok.text
    client.delete(f"/api/collections/{cid}")


@pytest.fixture
def fake_llm(monkeypatch):
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "fake")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        user = json.loads(request.content)["messages"][-1]["content"]
        if "두 지문을" in user:
            obj = {
                "questions": [
                    {
                        "question": "부당해고가 무효면 그 기간 임금은?",
                        "evidence_a": "정당한 이유 없이 해고하지 못한다",
                        "evidence_b": "해고 기간의 임금을 지급하여야 한다",
                    }
                ]
            }
        elif "답이 없는" in user:
            obj = {"questions": [{"question": "수습기간 해고 예고수당은 얼마인가요?", "missing": "수습 해고 예고수당 금액이 없음"}]}
        else:
            obj = {
                "questions": [
                    {"type": "condition", "question": "하루 10시간 주 5일이면?", "evidence": "1주 간의 근로시간은 40시간을 초과할 수 없다"}
                ]
            }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(obj, ensure_ascii=False)}}]})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))


def test_generate_hard_types(client, fake_llm):
    cid = client.post("/api/collections", json={"name": "어려운 질문"}).json()["id"]
    docs = {"근로기준법.txt": LAW + " " + "제50조(근로시간) ① 1주 간의 근로시간은 휴게시간을 제외하고 40시간을 초과할 수 없다." * 3,
            "판례.txt": CASE * 3, "임대차.txt": "주택임대차에서 보증금은 임대차가 끝난 뒤 돌려받는다. " * 6}  # fmt: skip
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in docs.items()])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert wait_job(client, cs["job"])["status"] == "done"
    body = {
        "chunk_set_id": cs["id"],
        "n_passages": 10,
        "min_chars": 20,
        "styles": ["condition", "multi", "unanswerable"],
        "n_multi": 2,
        "n_unanswerable": 2,
    }
    r = client.post(f"/api/collections/{cid}/eval-sets/generate", json=body).json()
    done = wait_job(client, r["job"])
    assert done["status"] == "done", done.get("error")
    items = client.get(f"/api/eval-sets/{r['id']}").json()["items"]
    types = {it["type"] for it in items}
    assert {"condition", "multi", "unanswerable"} <= types
    multi = next(it for it in items if it["type"] == "multi")
    una = next(it for it in items if it["type"] == "unanswerable")
    assert len(multi["doc_ids"]) == 2 and len(multi["evidences"]) == 2 and una["answerable"] is False and una["doc_ids"] == []
    client.delete(f"/api/collections/{cid}")


def test_import_public_corpus(client, monkeypatch):
    monkeypatch.setattr(
        public_corpus,
        "collect_statutes",
        lambda job, spec, lo, hi: [
            {
                "filename": "근로기준법.txt",
                "text": "근로기준법\n\n" + LAW,
                "source": {"kind": "statute", "license": "공공누리", "dataset": "d"},
            }
        ],
    )
    monkeypatch.setattr(public_corpus, "collect_precedents", lambda job, spec, lo, hi: [
        {"filename": "판례 1.txt", "text": CASE, "source": {"kind": "precedent", "license": "openrail", "dataset": "d2"}}])  # fmt: skip
    assert any(p["key"] == "labor_lease_law" for p in client.get("/api/public-corpora").json())
    cid = client.post("/api/collections", json={"name": "공개 자료"}).json()["id"]
    done = wait_job(
        client, client.post(f"/api/collections/{cid}/import-public", json={"preset": "labor_lease_law", "max_precedents": 5}).json()
    )
    assert done["status"] == "done" and done["result"]["added"] == 2 and done["result"]["by_kind"] == {"statute": 1, "precedent": 1}
    docs = client.get(f"/api/collections/{cid}").json()["documents"]
    assert {d["meta"]["source"]["license"] for d in docs} == {"공공누리", "openrail"}  # 출처 · 라이선스를 문서마다 남긴다
    assert client.post(f"/api/collections/{cid}/import-public", json={"preset": "없음"}).status_code == 400
    client.delete(f"/api/collections/{cid}")
