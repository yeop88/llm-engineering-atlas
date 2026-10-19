"""모델 호환성 점검 · Hub 새 모델 후보."""

from app.core import crud
from app.core.db import SessionLocal
from app.stages.embedding import compat, hub
from tests.helpers import model_id


def test_compat_check(client):
    mid = model_id(client, "nlpai-lab/KURE-v1")
    with SessionLocal() as db:
        spec = crud.get_spec(db, mid, "embedding")
        row = crud.get_model(db, mid)
        dim = row.dim
    good = compat.check(spec, None)
    assert good["ok"], good["issues"]
    assert good["dim"] and all(m > 0 for m in good["margins"])
    wrong = compat.check(spec, (good["dim"] or 0) + 1)
    assert not wrong["ok"] and any("차원 불일치" in i for i in wrong["issues"])
    res = compat.run_all(type("J", (), {"update": lambda *a, **k: None})(), [mid])
    assert res["n"] == 1 and res["run_id"] and "sentence-transformers" in res["versions"]
    last = client.get("/api/models/compat-check/last").json()
    assert last["run"]["n"] == 1 and last["upgrade_detected"] is False
    assert dim is None or isinstance(dim, int)


def test_discover_filters(monkeypatch):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)

    class M:
        def __init__(self, id_, likes, days, tags=()):
            self.id, self.likes, self.downloads, self.created_at = id_, likes, 10, now - timedelta(days=days)
            self.tags, self.gated, self.pipeline_tag, self.library_name = list(tags), False, "sentence-similarity", "sentence-transformers"

    models = [
        M("a/new-ko", 50, 10, ["ko"]),
        M("b/old", 900, 900),
        M("c/few-likes", 1, 5),
        M("d/x-GGUF", 99, 3, ["gguf"]),
        M("e/known", 80, 20),
        M("f/embeddinggemma-2-coreml", 30, 9),  # Core ML 변환본 — 처음 필터에서 새어 나왔던 것
        M("g/model_onnx", 30, 9),
        M("h/coreml-tagged-model", 30, 9, ["coreml"]),
    ]

    class Api:
        def list_models(self, **kw):
            return models

    monkeypatch.setattr(hub, "_api", lambda: Api())
    out = hub.discover({"e/known"}, set(), days=180, min_likes=10, force=True)
    assert [r["hf_id"] for r in out] == ["a/new-ko"] and out[0]["korean"]
