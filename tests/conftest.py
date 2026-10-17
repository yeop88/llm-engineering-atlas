import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

# app 모듈 import 전에 임시 데이터 디렉터리를 지정해야 DB 엔진이 그 경로로 만들어진다.
_TMP = tempfile.mkdtemp(prefix="embedding_lab_test_")
os.environ["DATA_DIR"] = _TMP
os.environ["MAX_LOADED_MODELS"] = "2"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeSentenceTransformer:
    """모델 다운로드 없이 인코딩 경로를 검증하기 위한 가짜 모델. 텍스트 해시로 결정적 벡터를 만든다."""

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
        vecs = []
        for text in inputs:
            rng = np.random.default_rng(abs(hash(prefix + str(text))) % 2**32)
            vecs.append(rng.standard_normal(self.dim))
        out = np.array(vecs, dtype=np.float32)
        if truncate_dim:
            out = out[:, :truncate_dim]
        if normalize_embeddings:
            out /= np.linalg.norm(out, axis=1, keepdims=True)
        return out


@pytest.fixture
def fake_model():
    return FakeSentenceTransformer(prompts={"query": "query: ", "document": "passage: "})


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import hub, model_manager

    monkeypatch.setattr(hub, "cache_status", lambda force=False: {})
    manager = model_manager.ModelManager(max_loaded=2)
    monkeypatch.setattr(model_manager, "_manager", manager)

    def fake_load(self, spec, multimodal, key):
        return model_manager.LoadedModel(
            key=key,
            spec=spec,
            profile=spec.profile_for(multimodal),
            model=FakeSentenceTransformer(prompts={"query": "query: ", "document": "passage: "}),
            device="cpu",
            dtype="float32",
            load_seconds=0.0,
            loaded_at=model_manager.datetime.now(model_manager.UTC),
        )

    monkeypatch.setattr(model_manager.ModelManager, "_load", fake_load)
    with TestClient(app) as c:
        yield c
