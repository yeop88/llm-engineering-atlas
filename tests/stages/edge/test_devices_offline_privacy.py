"""ED1 · ED2 기기별 조합 추천, ED4 오프라인 기능 범위, ED6 개인정보 국소 처리 — DB · 모델 없이 도는 부분."""

from datetime import timedelta

import pytest

from app.core.db import EdgeDevice, utcnow
from app.stages.edge import devices, offline, privacy
from app.stages.edge import sync as sy


# ── ED1 · ED2 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("text", "b"), [("308M", 0.308), ("740M (텍스트 270M)", 0.27), ("1.1B", 1.1), ("", None), ("모름", None)])
def test_params_b(text, b):
    # 멀티모달 모델은 글 모델 크기로 — 기기에서는 글 임베딩만 돌리므로 전체 크기로 재면 메모리를 부풀린다
    assert devices.params_b(text) == (pytest.approx(b) if b is not None else None)


FILES = [
    {"name": "gemma-4-E4B-it-Q4_K_M.gguf", "gb": 4.6},
    {"name": "gemma-4-E4B-it-Q8_0.gguf", "gb": 7.5},
    {"name": "Qwen3-4B-Q4_K_M.gguf", "gb": 2.4},
]


def test_match_file_alias_and_bits():
    # 실측 기록의 별칭 → GGUF 파일. 비트 표시가 없으면 서버 기본(Q4)으로 본다
    assert devices.match_file("gemma-4-e4b-q8", FILES)["name"] == "gemma-4-E4B-it-Q8_0.gguf"
    assert devices.match_file("gemma-4-e4b", FILES)["name"] == "gemma-4-E4B-it-Q4_K_M.gguf"
    assert devices.match_file("qwen3-4b", FILES)["name"] == "Qwen3-4B-Q4_K_M.gguf"
    assert devices.match_file("qwen3-4b-q8", FILES) is None  # 그 비트의 파일이 없으면 짝짓지 않는다(다른 비트의 품질을 붙이지 않게)
    assert devices.match_file("llama-3", FILES) is None


def test_gguf_files_skips_helpers_and_marks_vision(tmp_path):
    for n in ("gemma-4-E4B-it-Q4_K_M.gguf", "mmproj-gemma-4-E4B-it-f16.gguf", "mtp-draft.gguf", "Qwen3-4B-Q4_K_M.gguf"):
        (tmp_path / n).write_bytes(b"x" * 10)
    files = {f["name"]: f for f in devices.gguf_files(tmp_path)}
    # 비전 투영 · 추측 디코딩 보조 파일은 답변 모델 후보가 아니다
    assert set(files) == {"gemma-4-E4B-it-Q4_K_M.gguf", "Qwen3-4B-Q4_K_M.gguf"}
    assert files["gemma-4-E4B-it-Q4_K_M.gguf"]["vision"] and not files["Qwen3-4B-Q4_K_M.gguf"]["vision"]
    assert devices.gguf_files(None) == [] and devices.gguf_files(tmp_path / "없음") == []


def _vec(weight, precision, recall, ram, model_gb=0.6, base=0.9):
    return {"hf_id": "m", "weight": weight, "dim": 1024, "precision": precision, "label": "", "recall": recall, "base_recall": base,
            "bytes_per_vector": ram, "disk_per_vector": ram, "model_gb": model_gb, "source": "quant_vectors #1"}  # fmt: skip


def test_recommend_budget_score_and_pareto():
    vecs = [_vec("w_fp32", "float32", 0.9, 4096, model_gb=2.2), _vec("w_int8", "binary_rescore", 0.85, 1152, model_gb=0.6)]
    llms = [
        {"name": "big", "gb": 7.5, "ram_gb": 7.7, "quant": "q8_0", "quality": 0.9, "eval_set": "s", "source": "quant_llm #2"},
        {"name": "small", "gb": 2.4, "ram_gb": 2.6, "quant": "q4_k_m", "quality": 0.8, "eval_set": "s", "source": "quant_llm #2"},
        {"name": "unmeasured", "gb": 1.0, "ram_gb": 1.2, "quant": "q4_k_m"},
    ]
    r = devices.recommend({"budget_gb": 5, "disk_gb": 16}, vecs, llms, n_chunks=10_000)
    assert r["n_candidates"] == 8 and all(x["ram_gb"] <= 5 for x in r["with_llm"])
    assert "big" not in {x["llm"] for x in r["with_llm"]}  # 예산 초과
    top = r["with_llm"][0]
    # 조합 점수 = 검색 recall × 답변 품질 — 두 손실이 함께 깎인다
    assert top["llm"] == "small" and top["precision"] == "float32" and top["score"] == pytest.approx(0.9 * 0.8)
    assert top["loss"] == {"retrieval": 0.0, "answer": pytest.approx(0.1)}  # 가장 좋은 LLM(big) 대비 답변 손실
    light = next(x for x in r["with_llm"] if x["llm"] == "small" and x["precision"] == "binary_rescore")
    assert (
        light["score"] == pytest.approx(0.85 * 0.8)
        and light["loss"]["retrieval"] == pytest.approx(0.05)
        and light["ram_gb"] < top["ram_gb"]
    )
    # 품질을 모르는 LLM 은 점수를 추측하지 않고 맨 뒤('재야 할 후보')
    assert r["with_llm"][-1]["llm"] == "unmeasured" and r["with_llm"][-1]["score"] is None
    # 같은 메모리로 점수를 더 올릴 수 없는 조합만 파레토 앞줄
    scored = sorted((x for x in r["with_llm"] + r["search_only"] if x["score"] is not None), key=lambda x: x["ram_gb"])
    best = -1.0
    for x in scored:
        assert x["pareto"] == (x["score"] > best)
        best = max(best, x["score"])
    assert r["search_only"][0]["recall"] == 0.9 and r["nearest"] == []
    # 예산 안에 LLM 조합이 하나도 없으면 가장 가까운 것을 보여 준다(무엇을 줄여야 하는지)
    tiny = devices.recommend({"budget_gb": 2.5, "disk_gb": 4}, vecs, llms[:2], n_chunks=10_000)
    assert tiny["with_llm"] == [] and tiny["nearest"] and all(not x["fits"] for x in tiny["nearest"])
    assert any("저장 공간 초과" in o for x in tiny["nearest"] for o in x["over"]) or tiny["nearest"][0]["over"]


# ── ED4 ──────────────────────────────────────────────────────────────────────
def test_capabilities_by_pack_llm_and_age():
    tablet = devices.PROFILES["tablet"]
    none = {f["key"]: f["status"] for f in offline.capabilities(None, tablet, None, None, 72)}
    assert none["search"] == "no" and none["answer"] == "defer" and none["fresh"] == "no" and none["law"] == "defer"
    m = {"version": 3, "n_chunks": 120, "n_cache": 2}
    vis = {"name": "g.gguf", "ram_gb": 3.0, "vision": True}
    caps = {f["key"]: f for f in offline.capabilities(m, tablet, vis, 10, 72)}
    assert caps["search"]["status"] == "ok" and "v3" in caps["search"]["reason"] and caps["faq"]["status"] == "ok"
    assert caps["answer"]["status"] == "ok" and caps["photo"]["status"] == "ok" and caps["fresh"]["status"] == "ok"
    # 카메라 없는 기기는 비전 모델이 있어도 사진을 미룬다 · 오래된 자료는 '자료 기준 시각'과 함께
    phone = {f["key"]: f for f in offline.capabilities(m, devices.PROFILES["phone"], vis, 100, 72)}
    assert phone["photo"]["status"] == "defer" and phone["fresh"]["status"] == "defer" and "100시간" in phone["fresh"]["reason"]


def test_needs_server_rules():
    assert offline.needs_server("현행 시행령 개정 내용") == "law"
    assert offline.needs_server("이 조문을 인용한 판례는 몇 건") == "graph"
    assert offline.needs_server("세탁기 배수 필터 청소") is None


def test_answer_offline_modes():
    hit = {"answer": "필터를 청소하세요", "sources": [1], "similarity": 0.95}
    assert offline.answer_offline(hit, [], True, "law")["mode"] == "faq"  # 검증된 답이 있으면 무엇보다 먼저
    d = offline.answer_offline(None, [{"score": 0.9}], True, "law")
    assert d["mode"] == "defer" and d["defer"] == "law" and "연결되면" in d["reason"]
    # 근거가 약하면 지어내지 않고 서버 전체 자료로 미룬다
    assert offline.answer_offline(None, [{"score": 0.1}], True, None)["defer"] == "question"
    assert offline.answer_offline(None, [], True, None)["mode"] == "defer"
    assert offline.answer_offline(None, [{"score": 0.6}], True, None)["mode"] == "answer"
    assert offline.answer_offline(None, [{"score": 0.6}], False, None)["mode"] == "sources"  # LLM 없는 기기는 근거만


# ── ED5 기기 상태 ────────────────────────────────────────────────────────────
def test_device_status_flags():
    d = EdgeDevice(id="t1", name="t1", profile="tablet", pack="as", version=1, last_sync=utcnow() - timedelta(hours=100))
    st = sy.device_status(d, {"as": 3}, 72)
    # 같은 질문에 기기마다 다른 답이 나오는 원인 — 판 뒤처짐 · 오래 연결 안 됨
    assert not st["ok"] and any("v1 → v3" in f for f in st["flags"]) and any("연결 안 됨" in f for f in st["flags"])
    ok = sy.device_status(EdgeDevice(id="t2", name="t2", pack="as", version=3, last_sync=utcnow()), {"as": 3}, 72)
    assert ok["ok"] and ok["age_hours"] == 0.0
    gone = sy.device_status(EdgeDevice(id="t3", name="t3", pack="old", version=1, last_sync=None), {}, 72)
    assert gone["flags"] == ["서버에 없는 팩", "동기화 기록 없음"]


# ── ED6 ──────────────────────────────────────────────────────────────────────
EVENTS = [
    {"kind": "feedback", "payload": {"question": "김철수 010-1234-5678 로 연락 주세요", "rating": 2, "customer": "김철수 서울시",
                                     "photo": "base64...", "usage": "검색 3회", "memo": "test@example.com"}},
    {"kind": "log", "payload": {"customer": "이영희"}},
]  # fmt: skip


def test_prepare_applies_policy_per_field():
    out = privacy.prepare(EVENTS)
    assert len(out["events"]) == 1  # 남길 항목이 없는 기록은 통째로 빠진다
    p = out["events"][0]["payload"]
    assert "010-1234-5678" not in p["question"] and p["rating"] == 2
    assert "customer" not in p and "photo" not in p and "usage" not in p  # never · stats 는 값이 기기 밖으로 나가지 않는다
    assert "test@example.com" not in p["memo"]  # 정책에 없는 항목은 가린다(모르는 것은 가림)
    assert out["stats"]["usage"] == {"n": 1, "chars": len("검색 3회")} and out["report"]["dropped"] == ["customer", "photo"]
    assert sum(out["report"]["masked"].values()) >= 2
    assert EVENTS[0]["payload"]["question"].startswith("김철수 010")  # 원본을 바꾸지 않는다
    raw = privacy.prepare(EVENTS, {"question": "raw"})
    assert "010-1234-5678" in raw["events"][0]["payload"]["question"]


def test_inspect_rechecks_and_never_stores_raw():
    """기기 마스킹을 믿지 않는다 — 기기 앱 판이 제각각이라 새어 들어온 개인정보는 서버가 다시 찾아 가린 값만 저장하고 위반으로 남긴다."""
    stored, v = privacy.inspect({"question": "연락처 010-1234-5678", "customer": "김철수", "nested": {"x": ["a@b.com"]}})
    assert "customer" not in stored and "010-1234-5678" not in str(stored) and "a@b.com" not in str(stored)
    fields = {x["field"] for x in v}
    assert {"customer", "question", "nested.x[0]"} <= fields
    clean, none = privacy.inspect({"question": "필터 청소 방법", "rating": 5})
    assert none == [] and clean == {"question": "필터 청소 방법", "rating": 5}
