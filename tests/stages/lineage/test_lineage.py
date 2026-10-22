"""기반 모델 계보(LN1~LN6): 이름 → 계열 · 세대, 라이선스 어긋남, GGUF 머리말 · HF 설정 → 같은 모양, 계보 그래프(세대 · 양자화 · 파생) · 비교 · API.

모델 파일을 받지 않는다. GGUF 는 큰 모델 맵 테스트의 작은 GGUF 쓰기(write_gguf)로 머리말만 만들고, HF 는 config.json · 모델 카드를
가짜로 돌려준다(hf_hub_download · model_info 를 바꿈). 읽은 모델은 data/lineage/models.json 에 쌓이므로 테스트마다 비운다.
"""

import json

import pytest

from app.core.config import get_settings
from app.stages.lineage import graph, inspect
from tests.stages.bigmodel.test_bigmodel import F16, F32, write_gguf


@pytest.fixture(autouse=True)
def empty_store():
    """다른 테스트가 남긴 계보 저장소가 결과(모델 수 · 그래프)를 바꾸지 않게."""
    p = inspect.store_path(get_settings().data_dir)
    p.unlink(missing_ok=True)
    yield
    p.unlink(missing_ok=True)


def tiny_gguf(path, name: str, arch: str = "qwen3", base: str | None = None, license_: str = "apache-2.0", link: str = "") -> None:
    meta = {"general.architecture": arch, "general.basename": name, "general.size_label": "0.1B", "general.license": license_, "general.quantized_by": "tester",
            f"{arch}.block_count": 2, f"{arch}.embedding_length": 64, f"{arch}.attention.head_count": 4, f"{arch}.attention.head_count_kv": 2,
            f"{arch}.context_length": 4096}  # fmt: skip
    if link:
        meta["general.license.link"] = link
    if base:
        meta |= {"general.base_model.count": 1, "general.base_model.0.name": base, "general.base_model.0.organization": base.split("/")[0],
                 "general.base_model.0.repo_url": f"https://huggingface.co/{base}"}  # fmt: skip
    ts = [("token_embd.weight", [64, 100], F16)]
    for i in range(2):
        ts += [
            (f"blk.{i}.attn_norm.weight", [64], F32),
            (f"blk.{i}.attn_k.weight", [64, 32], F16),
            (f"blk.{i}.attn_v.weight", [64, 32], F16),
        ]
    write_gguf(path, meta, ts)


HF_CFG = {"model_type": "qwen3", "hidden_size": 1024, "num_hidden_layers": 28, "num_attention_heads": 16, "num_key_value_heads": 8, "head_dim": 128,
          "vocab_size": 151936, "intermediate_size": 3072, "max_position_embeddings": 40960, "tie_word_embeddings": True}  # fmt: skip


# ── LN3 계열 · 세대 · 라이선스 ───────────────────────────────────────────
@pytest.mark.parametrize(
    ("name", "fam", "gen"),
    [("Qwen/Qwen3-0.6B", "Qwen", "3"), ("google/gemma-4-E4B-it", "Gemma", "4"), ("kakaocorp/kanana-2-3b-instruct", "Kanana", "2"),
     ("LGAI-EXAONE/EXAONE-4.0-1.2B", "EXAONE", "4.0"), ("microsoft/phi-4", "Phi", "4"), ("someone/mystery", "기타", None)],
)  # fmt: skip
def test_family_generation(name, fam, gen):
    assert inspect.family(name)[0] == fam and inspect.generation(name) == gen


def test_license_check():
    ok = inspect.license_check("apache-2.0", "https://www.apache.org/licenses/LICENSE-2.0")
    assert not ok["check"] and ok["id"] == "apache-2.0"
    bad = inspect.license_check("apache-2.0", "https://ai.google.dev/gemma/terms")
    assert bad["check"] and "Gemma" in bad["notes"][0]  # id 와 링크가 다른 라이선스 — 배포 전에 확인
    assert inspect.license_check("other", None)["check"]  # 이름 없는 'other'
    assert not inspect.license_check("other", "https://ai.google.dev/gemma/terms", "gemma")["check"]  # 이름이 링크와 맞으면 괜찮다


# ── LN1 · LN2 읽기 ───────────────────────────────────────────────────────
def test_from_gguf(tmp_path):
    p = tmp_path / "kanana-2-mini_q4.gguf"
    tiny_gguf(p, "kanana-2-mini", base="kakaocorp/kanana-2-3b-instruct")
    m = inspect.from_gguf(p)
    assert m["key"] == "gguf:kanana-2-mini_q4.gguf" and m["source"] == "gguf"
    assert m["family"] == "Kanana" and m["arch"] == "qwen3"  # 계열은 이름이 먼저 — 빌려 쓴 구조 이름(qwen3)으로 정하지 않는다
    assert m["generation"] == "2" and m["layers"] == 2 and m["context"]["trained"] == 4096
    assert m["base_models"][0]["name"] == "kakaocorp/kanana-2-3b-instruct" and m["quantized_by"] == "tester"
    assert m["modalities"] == ["text"] and not m["mmproj"]
    (tmp_path / "kanana-2-mini-mmproj.gguf").write_bytes(b"x")  # 같은 폴더의 투영기 → 사진도 본다
    assert inspect.from_gguf(p)["modalities"] == ["text", "image"]


def test_from_hf():
    m = inspect.from_hf("Qwen/Qwen3-0.6B", HF_CFG, {"license": "apache-2.0", "base_model": "Qwen/Qwen3-0.6B-Base"})
    assert m["key"] == "hf:Qwen/Qwen3-0.6B" and m["family"] == "Qwen" and m["layers"] == 28 and m["kv_heads"] == 8
    assert m["base_models"][0]["repo"] == "https://huggingface.co/Qwen/Qwen3-0.6B-Base" and m["modalities"] == ["text"]
    vis = inspect.from_hf("google/gemma-4-E4B-it", {"text_config": HF_CFG, "vision_config": {"image_size": 768}, "audio_config": {}}, None)
    assert vis["modalities"] == ["text", "image"]  # audio_config 가 비어 있으면 소리는 없다고 본다
    assert vis["license"]["check"]  # 카드 없음 → 라이선스 이름 없음 → 확인 필요


def test_store_roundtrip(tmp_path):
    assert inspect.load(tmp_path) == {}
    inspect.save(tmp_path, {"a": {"x": 1}})
    assert inspect.load(tmp_path) == {"a": {"x": 1}}
    inspect.store_path(tmp_path).write_text("{깨진", encoding="utf-8")
    assert inspect.load(tmp_path) == {}  # 깨진 저장소는 빈 것으로(화면이 500 이 되지 않게)


# ── LN4~LN6 그래프 · 비교 ─────────────────────────────────────────────────
def test_graph_generations_and_quantized_from():
    q3 = inspect.from_hf("Qwen/Qwen3-0.6B", HF_CFG, {"license": "apache-2.0"})
    q25 = inspect.from_hf("Qwen/Qwen2.5-0.5B", HF_CFG | {"num_hidden_layers": 24}, {"license": "apache-2.0"})
    g = {"key": "gguf:q3.gguf", "source": "gguf", "name": "Qwen3-0.6B", "family": "Qwen", "org": "Alibaba Qwen", "generation": "3", "arch": "qwen3",
         "modalities": ["text"], "license": {"id": "apache-2.0"}, "base_models": [{"name": "Qwen/Qwen3-0.6B", "repo": "https://huggingface.co/Qwen/Qwen3-0.6B"}]}  # fmt: skip
    out = graph.build({q3["key"]: q3, q25["key"]: q25, g["key"]: g})
    rels = {(e["a"], e["rel"], e["b"]) for e in out["edges"]}
    assert ("gguf:q3.gguf", "QUANTIZED_FROM", "hf:Qwen/Qwen3-0.6B") in rels  # 같은 모델의 다른 비트
    assert ("hf:Qwen/Qwen3-0.6B", "SUCCEEDS", "hf:Qwen/Qwen2.5-0.5B") in rels  # 세대 순
    assert ("hf:Qwen/Qwen3-0.6B", "LICENSED_UNDER", "license:apache-2.0") in rels
    types = {n["id"]: n["type"] for n in out["nodes"]}
    assert types["family:Qwen"] == "Family" and types["mod:text"] == "Capability"
    assert len([n for n in out["nodes"] if n["id"] == "hf:Qwen/Qwen3-0.6B"]) == 1  # 기반 노드가 이미 있으면 겹치지 않는다
    ch = {c["field"]: (c["a"], c["b"]) for c in graph.compare(q3, q25)}
    assert ch["layers"] == (28, 24) and "license" not in ch


# ── API ──────────────────────────────────────────────────────────────────
def test_scan_inspect_graph_compare_delete(client, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_models_dir", tmp_path)
    tiny_gguf(
        tmp_path / "gemma-4-mini.gguf", "gemma-4-mini", arch="gemma3", license_="apache-2.0", link="https://ai.google.dev/gemma/terms"
    )
    (tmp_path / "broken.gguf").write_bytes(b"NOPE" + b"\0" * 20)
    r = client.post("/api/lineage/scan").json()
    assert r["read"] == ["gguf:gemma-4-mini.gguf"] and r["errors"][0]["file"] == "broken.gguf" and r["total"] == 1

    import huggingface_hub

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(HF_CFG), encoding="utf-8")

    class Card:
        pipeline_tag = "text-generation"
        card_data = {"license": "apache-2.0", "base_model": "Qwen/Qwen3-0.6B-Base"}

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda repo, fn: str(cfg))
    monkeypatch.setattr(huggingface_hub, "model_info", lambda repo: Card())
    m = client.post("/api/lineage/inspect", json={"hf_id": "Qwen/Qwen3-0.6B"}).json()
    assert m["key"] == "hf:Qwen/Qwen3-0.6B" and m["license"]["id"] == "apache-2.0" and m["base_models"][0]["name"] == "Qwen/Qwen3-0.6B-Base"

    ms = client.get("/api/lineage/models").json()["models"]
    assert {x["key"] for x in ms} == {"gguf:gemma-4-mini.gguf", "hf:Qwen/Qwen3-0.6B"}
    assert next(x for x in ms if x["source"] == "gguf")["license"]["check"]  # id apache · 링크 Gemma — 확인 필요
    g = client.get("/api/lineage/graph").json()
    assert {"gguf:gemma-4-mini.gguf", "hf:Qwen/Qwen3-0.6B"} <= {n["id"] for n in g["nodes"]}
    c = client.get("/api/lineage/compare", params={"a": "gguf:gemma-4-mini.gguf", "b": "hf:Qwen/Qwen3-0.6B"}).json()
    assert {x["field"] for x in c["changes"]} >= {"layers", "arch"}
    assert client.get("/api/lineage/compare", params={"a": "x", "b": "y"}).status_code == 404
    assert client.delete("/api/lineage/models/hf:Qwen/Qwen3-0.6B").json() == {"deleted": "hf:Qwen/Qwen3-0.6B"}
    assert client.delete("/api/lineage/models/hf:Qwen/Qwen3-0.6B").status_code == 404


def test_inspect_errors(client, tmp_path, monkeypatch):
    import huggingface_hub

    def missing(repo, fn):
        raise OSError("오프라인")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", missing)
    r = client.post("/api/lineage/inspect", json={"hf_id": "nobody/nothing"})
    assert r.status_code == 400 and "config.json" in r.json()["detail"]
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"model_type": "vit"}), encoding="utf-8")  # 언어 모델이 아님 — hidden_size 없음
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda repo, fn: str(cfg))
    monkeypatch.setattr(huggingface_hub, "model_info", lambda repo: (_ for _ in ()).throw(OSError("카드 없음")))
    r = client.post("/api/lineage/inspect", json={"hf_id": "google/vit-base"})
    assert r.status_code == 400 and "config.json" in r.json()["detail"]


@pytest.mark.parametrize("url", ["/lineage/models", "/lineage/graph"])
def test_pages_open(client, url):
    assert client.get(url).status_code == 200
