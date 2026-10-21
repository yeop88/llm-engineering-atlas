"""해석 가능성(IP1~IP6): 임베딩 공간 지표 · 언어 간 정렬, 작은 LLM 도구(근거 토큰 범위 · 은닉 상태 · 생성 신호 · 조종 훅 · 로그확률 ·
어텐션), 질문 두 벌 만들기, 탐침 · 방향 · 환각 AUROC, 희소 오토인코더, API.

실제 Qwen 을 받지 않는다 — 설정만으로 만든 아주 작은 무작위 Qwen2(층 2 · 차원 32, eager 어텐션)와 글자 단위 토크나이저로 '도구가 맞게
동작하는가'만 본다(무작위 모델이라 정확도 값 자체는 뜻이 없다).
"""

import numpy as np
import pytest
import torch
from transformers import Qwen2Config, Qwen2ForCausalLM

from app.stages.interp import inside, lm, sae, space
from tests.helpers import wait_job


class CharTok:
    """글자 하나 = 토큰 하나. 처음 본 글자에 번호를 붙여 되돌릴 수 있게."""

    eos_token, eos_token_id, pad_token = "</s>", 0, "</s>"

    def __init__(self):
        self.ids: dict[str, int] = {}
        self.chars: dict[int, str] = {}

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, **kw):
        return "".join(f"<{m['role']}>{m['content']}" for m in messages) + "<assistant>"

    def __call__(self, text, add_special_tokens=False):
        out = []
        for ch in text:
            if ch not in self.ids:
                i = 1 + len(self.ids) % 250
                self.ids[ch], self.chars[i] = i, ch
            out.append(self.ids[ch])
        return {"input_ids": out}

    def decode(self, ids, skip_special_tokens=True):
        return "".join(self.chars.get(int(i), "?") for i in ids)

    def convert_tokens_to_ids(self, t):
        return -1


@pytest.fixture
def tiny(monkeypatch):
    torch.manual_seed(0)
    model = Qwen2ForCausalLM(Qwen2Config(vocab_size=260, hidden_size=32, intermediate_size=64, num_hidden_layers=2, num_attention_heads=2,
                                         num_key_value_heads=1, max_position_embeddings=4096, attn_implementation="eager"))  # fmt: skip
    model.eval()
    tok = CharTok()
    monkeypatch.setattr(lm, "load", lambda hf_id=None: (model, tok))
    return model, tok


CTX = [
    {"filename": "AS안내", "text": "세탁기 배수가 안 될 때는 배수 필터를 청소하세요."},
    {"filename": "법령", "text": "공문서는 한글로 작성하여야 한다."},
]


def test_space_metrics_and_alignment():
    rnd = np.random.RandomState(0)
    iso = rnd.randn(300, 32)
    aniso = iso + 8.0  # 모두 한쪽으로 — 아무 두 글의 코사인이 1 에 가까워짐
    assert space.metrics(aniso)["anisotropy"] > 0.9 > space.metrics(iso)["anisotropy"]
    low = rnd.randn(300, 3) @ rnd.randn(3, 32)  # 실제로 3 차원만 씀
    assert space.metrics(low)["effective_dim"] < 4 and space.metrics(low)["pca_top10"] > 0.99
    docs = [i % 5 for i in range(300)]
    clustered = np.array([np.eye(32)[d] * 5 for d in docs]) + 0.1 * rnd.randn(300, 32)
    assert space.metrics(clustered, docs)["doc_separation"] > 0.5
    ko = rnd.randn(12, 32)
    a = space.alignment(ko, ko + 0.05 * rnd.randn(12, 32))
    assert a["retrieval@1"] == 1.0 and a["gap"] > 0.5 and len(space.PAIRS) == 12


def test_lm_tools(tiny):
    model, tok = tiny
    ids, spans = lm.prompt_ids(tok, "배수가 안 되면?", CTX)
    assert all(s is not None for s, _ in spans) and spans[0][1] > spans[0][0]
    hs = lm.hidden_last(model, ids, [0, 1, 2])
    assert set(hs) == {0, 1, 2} and len(hs[2]) == 32
    g = lm.generate(model, tok, ids, max_new=5)
    assert g["n_tokens"] == 5 and g["mean_entropy"] > 0 and 0 < g["min_prob"] <= 1
    vec = torch.ones(32) / 32**0.5
    before = len(model.model.layers[0]._forward_hooks)
    g2 = lm.generate(model, tok, ids, max_new=5, steer=(0, vec, 50.0))
    assert g2["text"] != g["text"] or g2["mean_entropy"] != g["mean_entropy"]  # 조종 훅이 실제로 출력을 바꾼다
    assert len(model.model.layers[0]._forward_hooks) == before  # 생성이 끝나면 우리 훅을 뗀다(transformers 가 단 훅은 그대로)
    assert lm.answer_logprob(model, tok, ids, "청소") < 0
    att = lm.attention_to_spans(model, ids, tok("청소하세요")["input_ids"], spans)
    assert all(a is not None and 0 <= a <= 1 for a in att) and sum(att) <= 1.0001


def test_pairs_with_and_without_gold():
    item = {"query": "배수", "evidence": "배수 필터를 청소하세요"}
    gold = {"text": "배수 필터를 청소하세요.", "filename": "g"}
    others = [{"text": f"관계없는 글 {i}", "filename": f"d{i}"} for i in range(4)]
    ps = inside.pairs([item, item], [[others[0], gold, *others[1:]], others], k=3)
    assert len(ps) == 1 and ps[0]["gold_index"] == 1 and gold not in ps[0]["without"] and len(ps[0]["without"]) == 3


def _rows(n=24, d=8, sep=3.0, seed=0):
    rnd = np.random.RandomState(seed)
    rows = []
    for i in range(n):
        kind = "without" if i % 2 else "with"
        h = rnd.randn(d) + (sep if kind == "without" else 0)
        rows.append({"kind": kind, "hidden": {4: h.tolist(), 8: rnd.randn(d).tolist()}, "refused": i % 4 == 3, "supported_ratio": 0.2 if kind == "without" else 0.9,
                     "mean_entropy": 2.0 if kind == "without" else 1.0, "min_prob": 0.1 if kind == "without" else 0.5})  # fmt: skip
    return rows


def test_probe_direction_hallucination():
    """뜻이 있는 층(4)만 탐침이 맞히고, 방향은 길이 1, 환각 AUROC 는 신호마다 같은 자료로."""
    rows = _rows()
    p = inside.probe(rows, [4, 8])
    assert p["best_layer"] == 4 and p["by_layer"][4] > 0.9 and p["by_layer"][4] > p["by_layer"][8]
    v = inside.direction(rows, 4)
    assert abs(float(v.norm()) - 1) < 1e-5 and float(v.mean()) > 0
    h = inside.hallucination(rows, 4)
    assert h["n"] == sum(not r["refused"] for r in rows) and h["auroc"]["평균 엔트로피"] == 1.0 and h["auroc"]["탐침 점수(층 4)"] > 0.9
    assert inside.refusal_rates(rows) == {"without_refused": 0.5, "with_refused": 0.0}
    only = [r | {"kind": "with"} for r in rows]
    assert inside.hallucination(only, None)["auroc"] == {}  # 두 종류가 다 있어야 잴 수 있다


def test_sae_trains_and_reports():
    torch.manual_seed(0)
    basis = torch.randn(6, 16)
    codes = torch.relu(torch.randn(800, 6)) * (torch.rand(800, 6) < 0.3)
    x = codes @ basis + 0.01 * torch.randn(800, 16)
    res = sae.train(x, mult=2, l1=1e-3, steps=300)
    assert res["n_features"] == 32 and res["explained"] > 0.5 and 0 < res["l0"] < 32
    where = [(i // 100, i % 100) for i in range(800)]
    toks = [[f"t{j}" for j in range(100)] for _ in range(8)]
    feats = sae.top_features(res, where, toks, k=3, n_ex=2)
    assert feats and all("⟦" in e for f in feats for e in f["examples"])
    xs, wh, tk2 = sae.token_states(*_tiny_model(), ["가나다", ""], 1)
    assert xs.shape[0] == 3 and wh[0] == (0, 0) and tk2[1] == []


def _tiny_model():
    torch.manual_seed(1)
    m = Qwen2ForCausalLM(Qwen2Config(vocab_size=260, hidden_size=16, intermediate_size=32, num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=1,
                                     attn_implementation="eager"))  # fmt: skip
    return m.eval(), CharTok()


def test_api(client, rag_collection, tiny):
    resp = client.post(
        "/api/interp/space", json={"model_ids": [rag_collection_model(client)], "collection_id": rag_collection["cid"], "max_chunks": 20}
    )
    assert resp.status_code == 202, resp.text
    r = wait_job(client, resp.json())
    assert r["status"] == "done", r
    m = r["result"]["models"][0]
    assert m["anisotropy"] is not None and "retrieval@1" in m["cross_lingual"]
    base = {"eval_set_id": rag_collection["set"], "max_queries": 2, "k": 2, "max_new": 8}
    resp = client.post("/api/interp/attribution", json=base)
    assert resp.status_code == 202, resp.text
    a = wait_job(client, resp.json())
    assert a["status"] == "done", a
    assert a["result"]["n"] >= 1 and len(a["result"]["rows"][0]["drops"]) == 2
    ins = wait_job(client, client.post("/api/interp/inside", json=base | {"layers": [1, 2], "name": "ip-test"}).json())
    assert ins["status"] == "done", ins
    assert set(ins["result"]["probe"]["by_layer"]) == {"1", "2"} or set(ins["result"]["probe"]["by_layer"]) == {1, 2}
    st = wait_job(client, client.post("/api/interp/steer", json={"name": "ip-test", "layer": 2, "alphas": [0, 5], "max_queries": 2}).json())
    assert st["status"] == "done", st
    assert [x["alpha"] for x in st["result"]["results"]] == [0, 5]
    assert client.post("/api/interp/steer", json={"name": "nope-missing", "max_queries": 2}).status_code == 404
    sa = wait_job(
        client,
        client.post("/api/interp/sae", json={"collection_id": rag_collection["cid"], "layer": 1, "max_texts": 10, "steps": 20}).json(),
    )
    assert sa["status"] == "done", sa
    assert sa["result"]["n_features"] == 128 and "ip-test" in client.get("/api/interp/overview").json()["saved"]


def rag_collection_model(client):
    from tests.helpers import model_id

    return model_id(client, "nlpai-lab/KURE-v1")
