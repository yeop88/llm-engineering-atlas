import json
import re

from app.catalog import CATALOG
from app.config import get_settings
from app.services.benchmark import list_datasets, validate_dataset

REQUIRED = ("hf_id", "name", "provider", "release_date", "params", "license", "languages")


def test_catalog_unique_and_complete():
    ids = [m["hf_id"] for m in CATALOG]
    assert len(ids) == len(set(ids)), "중복 hf_id"
    for m in CATALOG:
        for k in REQUIRED + (("dim",) if m.get("kind", "embedding") == "embedding" else ()):
            assert m.get(k), f"{m['hf_id']}: {k} 누락"
        assert m.get("kind", "embedding") in ("embedding", "reranker")
        assert re.fullmatch(r"[\w.\-]+/[\w.\-]+", m["hf_id"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", m["release_date"])
        assert m["release_date"] <= "2026-10-17"


def test_catalog_mrl_dims_valid():
    for m in CATALOG:
        dims = m.get("mrl_dims", [])
        assert dims == sorted(set(dims), reverse=True), m["hf_id"]
        assert all(d <= m["dim"] for d in dims), m["hf_id"]
    rerankers = [m for m in CATALOG if m.get("kind") == "reranker"]
    assert len(rerankers) >= 5 and all(not m.get("mrl_dims") for m in rerankers)


def test_embeddinggemma2_entry():
    m = next(x for x in CATALOG if x["hf_id"] == "google/embeddinggemma-2")
    assert m["dim"] == 768 and m["mrl_dims"] == [768, 512, 256, 128]
    assert m["query_prompt"] == "SearchQuery" and m["document_prompt"] == "Document"
    assert m["load_kwargs"]["config_kwargs"] == {"vision_config": None, "audio_config": None}
    assert "image" in m["modalities"]


def test_builtin_datasets_valid():
    for p in get_settings().datasets_dir.glob("*.json"):
        validate_dataset(json.loads(p.read_text(encoding="utf-8")))
    names = {d["name"] for d in list_datasets()}
    assert {"ko_en_retrieval_mini", "ko_sts_mini"} <= names
