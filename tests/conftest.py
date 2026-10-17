import os
import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np
import pytest

# app 모듈 import 전에 임시 데이터 디렉터리를 지정해야 DB 엔진이 그 경로로 만들어진다.
_TMP = tempfile.mkdtemp(prefix="embedding_lab_test_")
os.environ["DATA_DIR"] = _TMP
os.environ["MAX_LOADED_MODELS"] = "3"
os.environ["QDRANT_URL"] = ":memory:"  # 테스트는 서버 없이 메모리 Qdrant
os.environ["VECTOR_STORE"] = "qdrant"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 검색 순위까지 검증하는 테스트에서 쓰는 모델은 차원을 크게 해 해시 충돌을 줄인다
WIDE_MODELS = {"nlpai-lab/KURE-v1": 512}


def _bigram_vector(text: str, dim: int) -> np.ndarray:
    """글자 바이그램을 해시해 세는 결정적 임베딩 — 겹치는 표현이 많을수록 코사인이 높다."""
    v = np.zeros(dim, dtype=np.float32)
    t = "".join(text.lower().split())
    for i in range(max(1, len(t) - 1)):
        v[zlib.crc32(t[i : i + 2].encode()) % dim] += 1.0
    if not v.any():
        v[0] = 1.0
    return v


class FakeSentenceTransformer:
    """모델 다운로드 없이 인코딩 경로를 검증하기 위한 가짜 임베딩 모델."""

    def __init__(self, dim: int = 16, prompts: dict[str, str] | None = None):
        self.dim = dim
        self.prompts = prompts or {}
        self.max_seq_length = 128
        self.calls: list[dict] = []

    def get_embedding_dimension(self) -> int:
        return self.dim

    def encode(self, inputs, prompt_name=None, normalize_embeddings=False, truncate_dim=None, **kwargs):
        self.calls.append({"inputs": list(inputs), "prompt_name": prompt_name, "truncate_dim": truncate_dim, **kwargs})
        prefix = self.prompts.get(prompt_name, "") if prompt_name else ""
        out = np.array([_bigram_vector(prefix + str(t), self.dim) for t in inputs], dtype=np.float32)
        if truncate_dim:
            out = out[:, :truncate_dim]
        if normalize_embeddings:
            norms = np.linalg.norm(out, axis=1, keepdims=True)
            out /= np.where(norms == 0, 1, norms)
        return out


class FakeCrossEncoder:
    """가짜 리랭커: 질의와 문서가 공유하는 글자 바이그램 비율."""

    prompts: dict = {}
    max_length = 512

    def predict(self, pairs, batch_size=32, show_progress_bar=False, **kwargs):
        def grams(s):
            s = "".join(s.lower().split())
            return {s[i : i + 2] for i in range(len(s) - 1)}

        return np.array([len(grams(q) & grams(d)) / max(1, len(grams(q))) for q, d in pairs], dtype=np.float32)


@pytest.fixture
def fake_model():
    return FakeSentenceTransformer(prompts={"query": "query: ", "document": "passage: "})


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import hub, model_manager

    monkeypatch.setattr(hub, "cache_status", lambda force=False: {})
    manager = model_manager.ModelManager(max_loaded=3)
    monkeypatch.setattr(model_manager, "_manager", manager)

    def fake_load(self, spec, multimodal, key):
        model = (
            FakeCrossEncoder()
            if spec.is_reranker
            else FakeSentenceTransformer(dim=WIDE_MODELS.get(spec.hf_id, 16), prompts={"query": "query: ", "document": "passage: "})
        )
        return model_manager.LoadedModel(
            key=key,
            spec=spec,
            profile=spec.profile_for(multimodal),
            model=model,
            device="cpu",
            dtype="float32",
            load_seconds=0.0,
            loaded_at=model_manager.datetime.now(model_manager.UTC),
        )

    monkeypatch.setattr(model_manager.ModelManager, "_load", fake_load)
    with TestClient(app) as c:
        yield c
