import json
import os
import sys
import tempfile
import zlib
from pathlib import Path

import httpx
import numpy as np
import pytest

# app 모듈 import 전에 임시 데이터 디렉터리를 지정해야 DB 엔진이 그 경로로 만들어진다.
_TMP = tempfile.mkdtemp(prefix="llm_atlas_test_")
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


COLOR_WORDS = ["빨간색 사진", "초록색 사진", "파란색 사진"]


def _image_words(x) -> str | None:
    """가짜 멀티모달: 이미지 입력({"image": PIL} 또는 PIL)을 가장 강한 색 채널의 이름 글로 바꿔 '본다'.
    그래서 '빨간색' 질의가 빨간 그림 · 프레임과 가까워져, 실제 모델 없이 교차 검색 경로를 검증할 수 있다."""
    im = x.get("image") if isinstance(x, dict) else x
    if not hasattr(im, "getpixel"):
        return None
    mean = np.asarray(im.convert("RGB"), dtype=np.float32).reshape(-1, 3).mean(axis=0)
    return COLOR_WORDS[int(mean.argmax())]


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
        out = np.array([_bigram_vector(_image_words(t) or (prefix + str(t)), self.dim) for t in inputs], dtype=np.float32)
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
    from app.stages.embedding import hub, model_manager

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


from app.core import llm  # noqa: E402 — 환경 변수(DATA_DIR 등)를 먼저 정한 뒤 불러온다
from app.core.config import get_settings  # noqa: E402
from tests.helpers import DOCS, EVIDENCE, model_id, wait_job  # noqa: E402


# ── 여러 단계 테스트가 함께 쓰는 픽스처 (리랭킹 · 에이전트 · 강화학습 · 증류 · 연결 실행) ──
@pytest.fixture
def scripted_llm(monkeypatch):
    """요청 내용(시스템 지시)을 보고 단계별로 그럴듯한 응답을 돌려주는 가짜 LLM."""
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "fake")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")
    state = {"agent_calls": 0, "temps": []}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
        state["temps"].append(body.get("temperature"))
        state.setdefault("cache", []).append(body.get("cache_prompt"))
        if "재정렬기" in system:  # LLM 목록형 리랭커: 마지막 후보를 1위로, 나머지는 빠뜨림
            n = user.count("\n[")
            text = json.dumps({"order": [n]})
        elif "조사 도우미" in system:  # 에이전트: 검색 → 계산 → 답
            state["agent_calls"] += 1
            step = state["agent_calls"]
            obj = ({"thought": "다른 표현으로 찾아보자", "action": "search", "input": "세탁기 배수 필터"} if step == 1 else
                   {"thought": "계산", "action": "calc", "input": "2 * (3 + 4)"} if step == 2 else
                   {"thought": "충분", "action": "finish", "input": "배수 필터를 청소하세요 [S1]."})  # fmt: skip
            text = json.dumps(obj, ensure_ascii=False)
        elif "질문 생성" in system or "질문을" in system and "JSON" in system:
            text = json.dumps(
                {"questions": [{"type": "fact", "question": "세탁기 배수가 안 되면?", "evidence": "배수 필터를 청소하세요"}]},
                ensure_ascii=False,
            )
        else:  # RAG 답변: 온도가 높으면 인용 없는 답(보상이 낮음)
            text = "배수 필터를 청소하세요 [1]." if (body.get("temperature") or 0) < 0.5 else "잘 모르겠지만 기사님을 부르세요."
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"completion_tokens": 8}})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    return state


@pytest.fixture
def rag_collection(client):
    cid = client.post("/api/collections", json={"name": "후반 단계 테스트"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in DOCS.items()])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert wait_job(client, cs["job"])["status"] == "done"
    idx = client.post("/api/indexes", json={"chunk_set_id": cs["id"], "model_id": model_id(client, "nlpai-lab/KURE-v1")}).json()
    assert wait_job(client, idx["job"])["status"] == "done"
    docs = {d["filename"]: d["id"] for d in client.get(f"/api/collections/{cid}").json()["documents"]}
    s = client.post(f"/api/collections/{cid}/eval-sets", json={"name": "e", "items": [
        {"query": "세탁기 배수가 안 될 때", "doc_ids": [docs["AS안내.md"]], "evidence": EVIDENCE},
        {"query": "공문서 작성 문자", "doc_ids": [docs["법령.txt"]], "evidence": "공문서는 어문규범에 맞추어 한글로 작성하여야 한다"}]}).json()  # fmt: skip
    yield {"cid": cid, "cs": cs["id"], "idx": idx["id"], "set": s["id"], "docs": docs}
    client.delete(f"/api/collections/{cid}")
