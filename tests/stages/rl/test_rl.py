"""8b 강화학습: 보상 · 선호 쌍 · Best-of 평가."""

import json

from app.stages.rl import reward
from tests.helpers import EVIDENCE, wait_job


def test_reward_function():
    src = [{"text": EVIDENCE + ". 냉장고 소음은 수평 조절."}, {"text": "공문서는 한글로 쓴다"}]
    good = reward.reward("배수 필터를 청소하세요 [1].", src, EVIDENCE)
    bad = reward.reward("필터를 바꾸세요 [3].", src, EVIDENCE)
    refuse = reward.reward("근거에서 찾을 수 없습니다.", src, EVIDENCE)
    honest = reward.reward("근거에서 찾을 수 없습니다.", [{"text": "무관한 내용"}], EVIDENCE)
    assert good["total"] > bad["total"] and good["parts"]["evidence_cited"] == 1.0 and bad["parts"]["invalid_citation"] < 0
    assert refuse["parts"] == {"false_refusal": -1.0} and honest["parts"] == {"honest_refusal": 0.5}
    assert "too_long" in reward.reward("가" * 700 + " [1]", src)["parts"]


def test_rl_sample_preferences_and_export(client, rag_collection, scripted_llm):
    s = client.post(
        "/api/rl/sample", json={"question": "세탁기 배수", "config": {"mode": "dense", "index_id": rag_collection["idx"]}, "n": 2}
    ).json()
    c = s["candidates"]
    assert c[0]["temperature"] == 0.1 and c[0]["reward"] > c[1]["reward"] and s["best"] == 0  # 평소 답(후보 0)이 인용해 보상이 높다
    p = client.post("/api/rl/preferences", json={"question": s["question"], "context": s["context"], "chosen": c[0]["text"], "rejected": c[1]["text"],
                                                  "collection_id": rag_collection["cid"]}).json()  # fmt: skip
    listed = client.get("/api/rl/preferences").json()
    assert listed["counts"]["human"] >= 1 and any(x["id"] == p["id"] for x in listed["items"])
    line = json.loads(client.get("/api/rl/preferences/export?source=human").text.splitlines()[-1])
    assert (
        line["prompt"][0]["role"] == "system" and "근거:" in line["prompt"][1]["content"] and line["chosen"][0]["content"] == c[0]["text"]
    )
    assert client.delete(f"/api/rl/preferences/{p['id']}").status_code == 200


def test_rl_evaluate_job(client, rag_collection, scripted_llm):
    body = {
        "eval_set_id": rag_collection["set"],
        "config": {"mode": "dense", "index_id": rag_collection["idx"]},
        "n": 3,
        "margin": 0.3,
        "max_queries": None,
    }
    done = wait_job(client, client.post("/api/rl/evaluate", json=body).json())
    assert done["status"] == "done", done.get("error")
    r = done["result"]
    assert r["best_of_n"]["reward"] >= r["greedy"]["reward"] and r["n_queries"] == 2 and r["pairs_saved"] >= 1  # 보상 차 큰 쌍 자동 저장
    assert "diff" in r["quality_paired"]
