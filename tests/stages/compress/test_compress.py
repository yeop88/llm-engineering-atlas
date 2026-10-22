"""프롬프트 · KV 캐시 압축(KC1~KC6): 토큰 놀람 · 보호 토큰 · 질문 대조 · 기준선 · 보존률, KV 위치 고르기 · 자르기 · 이어 읽기 · 양자화 · 충실도, API.

실제 Qwen 을 받지 않는다 — 해석 맵 테스트와 같은 아주 작은 무작위 Qwen2(eager 어텐션)와 글자 단위 토크나이저로 '압축 · 캐시 조작이 맞게
동작하는가'만 본다. 가장 중요한 검사는 '모든 위치를 남기고 자른 캐시로 이어 읽으면 가득 찬 캐시와 로짓이 같다' — 위치 번호를 원래대로
이어 붙이는 처리가 맞다는 뜻이고, 그래야 정책 사이의 충실도 차이를 믿을 수 있다.
"""

import re

import pytest
import torch
from transformers import Qwen2Config, Qwen2ForCausalLM

from app.stages.compress import kv, prompt
from app.stages.interp import lm
from tests.helpers import wait_job
from tests.stages.interp.test_interp import CharTok

TEXT = "세탁기에서 E4 오류가 뜨면 배수 필터를 여세요. 제3조에 따라 30일 안에 신고하여야 한다. 오늘 날씨는 맑아요."


@pytest.fixture
def tiny(monkeypatch):
    torch.manual_seed(0)
    model = Qwen2ForCausalLM(Qwen2Config(vocab_size=260, hidden_size=32, intermediate_size=64, num_hidden_layers=2, num_attention_heads=2,
                                         num_key_value_heads=1, max_position_embeddings=4096, attn_implementation="eager"))  # fmt: skip
    model.eval()
    tok = CharTok()
    monkeypatch.setattr(lm, "load", lambda hf_id=None: (model, tok))
    return model, tok


def _subsequence(small: str, big: str) -> bool:
    it = iter(big)
    return all(ch in it for ch in small)


# ── 프롬프트 압축 (KC1 · KC2) ───────────────────────────────────────────
def test_sentences_and_surprisal(tiny):
    model, tok = tiny
    assert prompt.sentences(TEXT) == [
        "세탁기에서 E4 오류가 뜨면 배수 필터를 여세요.",
        "제3조에 따라 30일 안에 신고하여야 한다.",
        "오늘 날씨는 맑아요.",
    ]
    ids, s = prompt.surprisal(model, tok, "배수 필터")
    assert len(ids) == len(s) == 5 and s[0] == 99.0 and all(0 < x < 99 for x in s[1:])  # 첫 토큰은 앞 문맥이 없어 지우지 않게
    _, with_prefix = prompt.surprisal(model, tok, "배수 필터", prefix="질문: ")
    assert with_prefix[0] < 99 and with_prefix != s  # 앞에 붙인 글이 조건이 된다
    assert prompt.surprisal(model, tok, "") == ([], [])


def test_token_compress_keeps_protected_and_order(tiny):
    model, tok = tiny
    r = prompt.token_compress(model, tok, TEXT, 0.2)
    assert r["total"] == len(TEXT) and r["kept"] >= r["protected"]
    assert all(d in r["text"] for d in "430")  # 숫자는 놀람과 상관없이 남긴다 — 하나만 빠져도 답이 틀린다
    assert prompt.preserved(TEXT, r["text"]) == 1.0  # 여러 토큰에 걸친 코드(E4) · 조문(제3조)도 통째로
    assert _subsequence(r["text"].replace(" ", ""), TEXT.replace(" ", ""))  # 남은 토큰은 원래 순서로
    half = prompt.token_compress(model, tok, TEXT, 0.5)
    assert abs(half["kept"] - round(len(TEXT) * 0.5)) <= 1
    assert prompt.token_compress(model, tok, "", 0.5)["total"] == 0


def test_protection_spans_cover_split_tokens():
    """빠른 토크나이저(offset_mapping)가 'E4' 를 'E' · '4' 로, '제3조' 를 '제' · '3' · '조' 로 나눠도 셋 다 지킨다."""

    class OffsetTok:
        def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
            pieces = [(m.start(), m.end()) for m in re.finditer(r"\S", text)]  # 글자마다 토큰, 공백은 버림
            out = {"input_ids": list(range(len(pieces)))}
            if return_offsets_mapping:
                out["offset_mapping"] = pieces
            return out

    text = "코드 E4 와 제3조 그리고 끝"
    tok = OffsetTok()
    ids = tok(text)["input_ids"]
    prot = prompt._protected(tok, text, ids)
    chars = [text[a:b] for a, b in tok(text, return_offsets_mapping=True)["offset_mapping"]]
    assert [c for c, p in zip(chars, prot, strict=True) if p] == ["E", "4", "제", "3", "조"]


class ByteTok(CharTok):
    """바이트 단위 BPE 흉내: 한글 한 글자(3바이트)를 토큰 3개로 쪼갠다 — 실제 Qwen 토크나이저처럼 토큰 하나만 지우면 글자가 깨진다."""

    def __call__(self, text, add_special_tokens=False, **kw):
        return {"input_ids": [b + 1 for b in text.encode("utf-8")]}

    def decode(self, ids, skip_special_tokens=True):
        return bytes(int(i) - 1 for i in ids).decode("utf-8", errors="replace")


@pytest.fixture
def tiny_bytes(monkeypatch):
    torch.manual_seed(0)
    model = Qwen2ForCausalLM(Qwen2Config(vocab_size=260, hidden_size=32, intermediate_size=64, num_hidden_layers=2, num_attention_heads=2,
                                         num_key_value_heads=1, max_position_embeddings=4096, attn_implementation="eager"))  # fmt: skip
    model.eval()
    return model.eval(), ByteTok()


def test_compression_never_breaks_characters(tiny_bytes):
    """바이트로 쪼개지는 토크나이저에서도 압축한 글에 깨진 글자(�)가 없어야 한다 — 실측에서 이것 때문에 정답률이 무너졌다."""
    model, tok = tiny_bytes
    for unit in ("char", "word"):
        for ratio in (0.2, 0.4, 0.7):
            r = prompt.token_compress(model, tok, TEXT, ratio, unit=unit)
            assert "\ufffd" not in r["text"], (unit, ratio, r["text"])
            assert prompt.preserved(TEXT, r["text"]) == 1.0
    words = prompt.token_compress(model, tok, TEXT, 0.4, unit="word")["text"].split()
    assert all(w in TEXT.split() for w in words)  # 어절 단위는 원문 어절을 통째로 남기거나 지운다
    q = prompt.query_compress(model, tok, TEXT, "E4 오류는?", 0.4)
    assert "\ufffd" not in q["text"]


def test_query_compress_scores_sentences_then_tokens(tiny):
    model, tok = tiny
    r = prompt.query_compress(model, tok, TEXT, "E4 오류는 어떻게 하나요?", 0.3)
    assert len(r["sentences"]) == 3 and all("score" in s for s in r["sentences"])
    assert any(s["kept"] for s in r["sentences"]) and not all(s["kept"] for s in r["sentences"])  # 목표의 두 배까지만 문장을 남긴다
    assert r["kept"] < r["total"] and _subsequence(r["text"].replace(" ", ""), TEXT.replace(" ", ""))
    full = prompt.query_compress(model, tok, TEXT, "질문", 1.0)
    assert all(s["kept"] for s in full["sentences"])


def test_baselines_and_preserved(tiny):
    _, tok = tiny
    lex = prompt.lexical_compress(TEXT, "배수 필터는 어떻게 여나요", 0.3)
    assert lex["text"].startswith("세탁기에서 E4") and "날씨" not in lex["text"]  # 질문과 글자가 겹치는 문장부터
    a, b = prompt.random_compress(tok, TEXT, 0.4, seed=1), prompt.random_compress(tok, TEXT, 0.4, seed=1)
    assert a == b and a["kept"] == round(len(TEXT) * 0.4)
    assert prompt.preserved(TEXT, TEXT) == 1.0
    # 원문의 표시: 제3조 · E4 · 숫자(4 · 3 · 30) — '제3조' 만 남기면 일부만
    p = prompt.preserved(TEXT, "제3조 신고")
    assert 0 < p < 1
    assert prompt.preserved("숫자 없는 글", "아무거나") is None


# ── KV 캐시 (KC3 ~ KC5) ─────────────────────────────────────────────────
def test_choose_policies():
    n, keep = 100, 20
    assert kv.choose("full", n, keep, []) == list(range(n))
    assert kv.choose("window", n, keep, []) == list(range(80, 100))
    sw = kv.choose("sink_window", n, keep, [])
    assert sw[:4] == [0, 1, 2, 3] and sw[-1] == 99 and len(sw) == keep  # 첫 토큰(주의 싱크) + 최근 창
    att = torch.zeros(2, n, n)
    att[:, :, 50] = 1.0  # 모든 질의가 50 번 토큰을 본다
    heavy = kv.choose("heavy", n, keep, [att])
    assert 50 in heavy and {0, 1, 2, 3} <= set(heavy) and 99 in heavy and len(heavy) == keep
    obs = torch.zeros(2, n, n)
    obs[:, -16:, 30] = 1.0  # 프롬프트 끝(질문) 쪽만 30 번을 본다
    obs[:, :10, 60] = 5.0  # 앞쪽 질의는 60 번을 본다 — 관찰 창 밖이라 snap 은 무시
    snap = kv.choose("snap", n, keep, [obs])
    assert 30 in snap and 60 not in snap
    assert 60 in kv.choose("heavy", n, keep, [obs])


def test_sliced_cache_with_all_positions_matches_full(tiny):
    """모든 위치를 남겨 자른 캐시로 이어 읽으면 가득 찬 캐시와 같아야 한다 — 위치 번호 처리가 맞다는 검사."""
    model, tok = tiny
    ids = tok(TEXT)["input_ids"]
    ans = kv.greedy_answer(model, tok, ids, 6)
    cache, last, atts = kv.prefill(model, ids, attentions=True)
    assert atts and atts[0].shape[-1] == len(ids)  # eager 어텐션이라 층별 어텐션이 나온다
    ref = kv.continue_logits(model, cache, last, ans, len(ids))
    c2, last2, _ = kv.prefill(model, ids)
    kv.slice_cache(c2, list(range(len(ids))))
    got = kv.continue_logits(model, c2, last2, ans, len(ids))
    f = kv.fidelity(ref, got, ans)
    assert f["top1"] == 1.0 and f["kl"] < 1e-6 and f["diverge_at"] is None
    # 이어 읽기 로짓이 탐욕 답과 맞는다 — 기준 자체가 맞게 만들어졌는지
    assert [int(torch.argmax(x)) for x in ref] == ans


def test_run_one_policies_and_quant(tiny):
    model, tok = tiny
    ids = tok(TEXT)["input_ids"]
    ans = kv.greedy_answer(model, tok, ids, 5)
    rows = kv.run_one(model, tok, ids, ans, ["full", "window", "sink_window", "heavy", "snap"], [0.5, 0.2], [(8, 8), (2, 2)])
    by = {(r["policy"], r["keep"]): r for r in rows}
    assert by[("full", 1.0)]["top1"] == 1.0 and by[("full", 1.0)]["kl"] < 1e-6
    assert by[("window", 0.2)]["kept_tokens"] == int(len(ids) * 0.2)
    assert all(0 <= r["top1"] <= 1 and r["kl"] >= 0 for r in rows)
    q8, q2 = by[("quant k8/v8", 1.0)], by[("quant k2/v2", 1.0)]
    assert q8["kl"] <= q2["kl"]  # 비트가 적을수록 더 흔들린다
    assert kv.run_one(model, tok, ids, [], ["full"], [0.5]) == []


def test_quantize_levels():
    class L:
        keys = torch.linspace(-1, 1, 64).reshape(1, 1, 8, 8)
        values = torch.linspace(-1, 1, 64).reshape(1, 1, 8, 8)

    class C:
        layers = [L()]

    c = C()
    kv.quantize_(c, 2, None)
    assert len(torch.unique(c.layers[0].keys[0, 0, 0])) <= 3  # 2비트 대칭 = −1 · 0 · +1 눈금
    assert len(torch.unique(c.layers[0].values)) == 64  # 값은 그대로(키만 줄임)


# ── API ─────────────────────────────────────────────────────────────────
def test_api_options_and_preview(client, tiny):
    o = client.get("/api/compress/options").json()
    assert set(o["methods"]) == {"none", "token", "word", "query", "lexical", "random"} and "snap" in o["policies"]
    lex = client.post("/api/compress/preview", json={"text": TEXT, "question": "배수 필터", "method": "lexical", "ratio": 0.3}).json()
    assert lex["char_ratio"] < 1 and lex["orig_chars"] == len(TEXT)
    tk = client.post("/api/compress/preview", json={"text": TEXT, "method": "token", "ratio": 0.3}).json()
    assert tk["preserved"] is not None and tk["preserved"] > 0.5 and tk["kept"] < tk["total"]


def test_api_eval_and_kv_jobs(client, tiny, scripted_llm, rag_collection):
    body = {"eval_set_id": rag_collection["set"], "methods": ["none", "lexical", "token"], "ratios": [0.5], "max_queries": 2}
    res = wait_job(client, client.post("/api/compress/eval", json=body).json(), 800)
    assert res["status"] == "done", res
    out = {r["method"]: r for r in res["result"]["results"]}
    assert set(out) == {"none", "lexical", "token"} and out["none"]["char_ratio"] == 1.0
    assert out["token"]["char_ratio"] < 1.0 and res["result"]["run_id"]
    kvres = wait_job(client, client.post("/api/compress/kv", json={"eval_set_id": rag_collection["set"], "policies": ["full", "sink_window"],
                                                                   "keeps": [0.5], "kv_bits": [[8, 8]], "max_queries": 1, "max_new": 4}).json(), 800)  # fmt: skip
    assert kvres["status"] == "done", kvres
    pol = {(r["policy"], r["keep"]): r for r in kvres["result"]["results"]}
    assert pol[("full", 1.0)]["top1"] == 1.0 and ("sink_window", 0.5) in pol and ("quant k8/v8", 1.0) in pol
    assert client.post("/api/compress/kv", json={"eval_set_id": 99999}).status_code == 400
