"""토크나이저 · 표현 공간(TK1~TK6): 토큰 효율 · 표시 쪼개짐 · 어휘 · 정규화 · 설정 비용 · 비교 작업 · API.

토크나이저를 받지 않는다. 바이트 단위 BPE 를 흉내 낸 가짜(UTF-8 바이트 하나 = 토큰 하나)로 '한글 한 글자가 바이트 조각으로 쪼개짐'을
재현하고, config.json 은 임시 파일로 준다 — 압축 맵에서 한글을 깨뜨렸던 바로 그 쪼개짐을 표시 검사가 잡는지 보려는 것이다.
"""

import json

import pytest

from app.stages.tokenizer import analyze
from tests.helpers import wait_job


class ByteTok:
    """UTF-8 바이트 하나 = 토큰 하나. 한글은 글자당 3토큰, 혼자 풀면 깨진 글자(�)."""

    all_special_tokens = ["<|endoftext|>"]

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": list(text.encode("utf-8"))}

    def decode(self, ids):
        return bytes(ids).decode("utf-8", errors="replace")

    def get_vocab(self):
        v = {chr(i): i for i in range(32, 127)}
        v |= {"가": 300, "세탁": 301, "기": 302}  # 한글이 든 조각 — 한 글자 조각 2개(가 · 기)
        return v

    def convert_tokens_to_string(self, toks):
        return "".join(toks)


@pytest.fixture
def fake_hub(monkeypatch, tmp_path):
    """토크나이저 · config.json 을 받지 않게 — 'bad/x' 는 없는 저장소처럼 실패."""
    cfg = {"vocab_size": 1000, "hidden_size": 64, "tie_word_embeddings": False, "rope_theta": 1e6, "max_position_embeddings": 32768,
           "vision_config": {"image_size": 224, "patch_size": 16, "spatial_merge_size": 2}}  # fmt: skip
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")

    def load(hid):
        if hid.startswith("bad/"):
            raise OSError("없는 저장소")
        return ByteTok()

    def download(hid, name):
        if hid.startswith("bad/"):
            raise OSError("없는 저장소")
        return str(p)

    monkeypatch.setattr(analyze, "load", load)
    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)


def test_efficiency_counts_tokens_per_char():
    eff = analyze.efficiency(ByteTok(), {"한": "가나다", "영": "abc"})
    # 한글은 글자당 3바이트 = 3토큰, 영어는 1 — 같은 글자 수에 맥락을 3배 쓴다
    assert eff["한"]["tokens_per_char"] == 3.0 and eff["영"]["tokens_per_char"] == 1.0
    assert eff["한"]["per_1000_chars"] == 3000


def test_marks_flag_byte_split_only_for_hangul():
    rows = {r["mark"]: r for r in analyze.marks(ByteTok())}
    assert rows["E4"]["byte_split"] is False and rows["E4"]["tokens"] == 2
    # '제3조의2' 는 한글이 들어 바이트 조각으로 쪼개진다 — 토큰 단위로 지우면 글자가 깨지는 자리
    assert rows["제3조의2"]["byte_split"] is True


def test_vocab_and_normalization():
    v = analyze.vocab(ByteTok())
    assert v["hangul_pieces"] == 3 and v["hangul_single_syllables"] == 2
    n = analyze.normalization(ByteTok())
    assert n["NFC(보통)"]["vs_nfc"] == 1.0
    # 바이트 토크나이저는 정규화하지 않는다 — 자모로 나눈 글 · 보이지 않는 문자는 토큰이 는다(정제가 필요하다는 신호)
    assert n["NFD(자모 분리)"]["vs_nfc"] > 1.0 and n["보이지 않는 문자"]["vs_nfc"] > 1.0


def test_config_costs_and_errors(fake_hub):
    c = analyze.config_costs("org/m")
    assert c["embedding_params_m"] == 0.1 and c["head_params_m"] == 0.1 and c["tied"] is False
    assert c["image_tokens"] == (224 // 16) ** 2 // 4 and c["rope"]["theta"] == 1e6
    assert "error" in analyze.config_costs("bad/x")


def test_compare_relative_to_best_and_errors(fake_hub):
    r = analyze.compare(["org/a", "org/b", "bad/x"])
    ok = [m for m in r["models"] if "efficiency" in m]
    assert len(ok) == 2 and all(m["efficiency"]["법령"]["vs_best"] == 1.0 for m in ok)
    bad = next(m for m in r["models"] if m["hf_id"] == "bad/x")
    assert "error" in bad  # 받지 못한 모델은 비교를 멈추지 않고 이유만 남긴다


def test_api(client, fake_hub):
    s = client.get("/api/tokenizer/samples").json()
    assert "법령" in s["samples"] and "WM-200" in s["marks"]
    job = wait_job(client, client.post("/api/tokenizer/compare", json={"hf_ids": ["org/a"]}).json())
    assert job["status"] == "done", job
    assert job["result"]["models"][0]["vocab"]["size"] > 0 and job["result"]["run_id"]
    assert client.post("/api/tokenizer/compare", json={"hf_ids": []}).status_code == 422
    assert client.get("/tokenizer/compare").status_code == 200
