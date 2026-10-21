"""후학습(P1~P7): 학습 데이터 선별 · 누수 차단, 프롬프트 모양 · 답 부분만 손실, SFT · DPO 고리, 앱 안 OpenAI 호환 끝점, GGUF 변환 명령.

실제 모델을 받지 않는다 — tests/stages/posttrain/fake_lm.py 의 글자 단위 가짜 모델로 학습 고리를 돌고, 변환은 명령만 확인하거나
subprocess 를 가짜로 바꾼다.
"""

import json
import math
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.core.db import AppModel, EvalSet, SessionLocal
from app.stages.distill import llm_data
from app.stages.posttrain import data, export, local_llm, trainer
from app.stages.rag import answer
from tests.helpers import wait_job
from tests.stages.posttrain.fake_lm import FakeJob, FakeLM, FakeTok, V


def _row(q, a="답 [1].", ctx="[1] 근거", src="distill:x"):
    return llm_data.sample(q, ctx, a) | {"_src": src}


class FakeDB:
    """select_rows · synth_refusals 가 쓰는 db.get 만 흉내 낸다(평가 세트 번호 → 항목)."""

    def __init__(self, sets):
        self.sets = sets

    def get(self, model, sid):
        assert model is EvalSet
        return self.sets.get(sid)


# ── P1 · P2 데이터 ─────────────────────────────────────────────────────────
def test_data_dir_is_test_temp():
    # 테스트가 만든 데이터 · 모델이 실제 data/ 를 더럽히지 않게 — conftest 가 DATA_DIR 을 임시 폴더로 정한다
    assert str(data.root()).startswith(tempfile.gettempdir()) and "llm_atlas_test_" in str(data.root())


def test_question_of_takes_last_question():
    assert data.question_of(_row("연차휴가는 며칠인가요?")) == "연차휴가는 며칠인가요?"
    # 근거(FAQ 문서)에 '질문:' 글이 있어도 실제 질문은 마지막 '질문:' 뒤 — 첫 번째에서 자르면 근거까지 질문으로 읽혀 중복 · 누수 검사가 틀린다
    faq = _row("보증금은 언제 돌려받나요?", ctx="[1] (FAQ.md)\n질문: 세탁기 소음은?\n답변: 수평을 맞추세요.")
    assert data.question_of(faq) == "보증금은 언제 돌려받나요?"
    dpo = {"prompt": [{"role": "system", "content": "s"}, {"role": "user", "content": answer.user_prompt("해고 예고는?", "c")}]}
    assert data.question_of(dpo) == "해고 예고는?"  # DPO 행은 prompt 에서 읽는다
    assert data.question_of({"messages": [{"role": "user", "content": "그냥 글"}]}) == "그냥 글"


def test_select_rows_format_dedup_leak():
    rows = [
        _row("세탁기 배수가 안 될 때 어떻게 하나요?"),
        _row("세탁기 배수가 안 될 때 어떻게 하나요?!", src="flywheel"),  # 거의 같은 질문 — 같은 예시를 두 번 배우면 그 답만 외운다
        _row("냉장고 소음을 줄이는 방법은?", src="refusal:3"),
        _row("근로계약서는 언제 써야 하나요?", src="flywheel"),  # 평가 세트 질문과 같음 → 누수
        {"messages": [{"role": "system", "content": "s"}], "_src": "distill:x"},  # 질문 없음
        {"prompt": [{"role": "user", "content": "질문: 선호만 있고 rejected 없음"}], "chosen": [{"content": "a"}], "_src": "pref:x"},
    ]
    db = FakeDB({9: SimpleNamespace(items=[{"query": "근로계약서는 언제 써야 하나요"}])})
    kept, rep = data.select_rows(db, rows, [9, 404])  # 없는 세트 번호는 건너뛴다
    # 단계별 남은 건수 — 데이터가 어디서 왜 줄었는지 설명할 수 있어야 한다
    assert (rep["in"], rep["format_ok"], rep["dedup"], rep["no_leak"]) == (6, 4, 3, 2)
    assert rep["leaked_examples"] == ["근로계약서는 언제 써야 하나요?"]
    assert rep["by_source"] == {"distill": 1, "refusal": 1}  # 출처는 ':' 앞까지로 묶는다
    assert [data.question_of(r) for r in kept] == ["세탁기 배수가 안 될 때 어떻게 하나요?", "냉장고 소음을 줄이는 방법은?"]


def test_synth_refusals_from_unanswerable():
    items = [{"query": "세탁기 배수", "doc_ids": [1]}, {"query": "화성 이주 비용은?", "answerable": False},
             {"query": "달 착륙 날짜는?", "doc_ids": []}, {"query": "세 번째 답 없는 질문", "answerable": False}]  # fmt: skip
    calls = []

    def search(cid, q):
        calls.append((cid, q))
        return [{"filename": "AS안내.md", "text": "세탁기 배수 필터를 청소하세요."}]

    out = data.synth_refusals(FakeDB({1: SimpleNamespace(collection_id=7, items=items)}), [1, 2], search, limit=2)
    # 답 없는 질문만, 실제 검색 근거와 함께 → '근거에서 찾을 수 없습니다' — 근거가 있어도 관련 없으면 거절을 배우게
    assert [c[1] for c in calls] == ["화성 이주 비용은?", "달 착륙 날짜는?"] and all(c[0] == 7 for c in calls)
    assert len(out) == 2 and out[0]["_src"] == "refusal:1"
    msgs = out[0]["messages"]
    assert (
        msgs[-1]["content"] == f"{answer.NOT_FOUND}." and "세탁기 배수 필터" in msgs[1]["content"] and msgs[0]["content"] == answer.SYSTEM
    )


def test_from_distill_reads_jsonl(monkeypatch, tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps(_row("질문 하나"), ensure_ascii=False) + "\n\n", encoding="utf-8")
    monkeypatch.setattr(llm_data, "file_path", lambda n: p)
    rows = data.from_distill(["t.jsonl"])
    assert len(rows) == 1 and rows[0]["_src"] == "distill:t.jsonl"  # 빈 줄은 건너뛰고, 출처를 붙여 선별 보고에 남긴다


def test_save_load_datasets_roundtrip():
    name = "pt_test_roundtrip"
    try:
        meta = data.save(name, [_row("저장 질문")], {"in": 1}, "sft")
        assert meta == {"name": name, "kind": "sft", "n": 1, "report": {"in": 1}}
        rows = data.load(name)
        assert "_src" not in rows[0] and rows[0]["messages"][-1]["content"] == "답 [1]."  # 내부 표시(_로 시작)는 학습 파일에 넣지 않는다
        assert any(d["name"] == name for d in data.datasets())
        # 이름에 경로 문자를 허용하면 데이터 폴더 밖에 파일을 쓸 수 있다
        with pytest.raises(ValueError):
            data.save("../bad", [], {}, "sft")
        with pytest.raises(ValueError):
            data.load("없는-이름")
    finally:
        for f in (data.root() / "datasets").glob(f"{name}*"):
            f.unlink()


# ── P3 · P4 프롬프트 · 학습 ────────────────────────────────────────────────
def test_prompt_ids_use_generation_prompt_without_thinking():
    tok = FakeTok()
    ids = trainer._prompt_ids(tok, [{"role": "user", "content": "ab"}])
    assert len(ids) == len("<user>ab<assistant>")
    # 학습 · 끝점 · GRPO 가 같은 모양으로 — 생각 블록을 끄지 않으면 Qwen3 가 답 대신 생각 글을 배운다
    assert tok.template_kwargs[-1] == {"add_generation_prompt": True, "enable_thinking": False}


def test_pair_keeps_answer_when_too_long():
    tok = FakeTok()
    prompt = [{"role": "user", "content": "가" * 200}]
    p_len = len(trainer._prompt_ids(tok, prompt))
    ids, start = trainer._pair(tok, prompt, "정답이다", 64)
    a = tok("정답이다</s>")["input_ids"]
    # 길면 근거(가운데)를 잘라 답을 남긴다 — 답이 잘리면 배울 것이 없다
    assert len(ids) == 64 and ids[start:] == a and start == 64 - len(a)
    full, s2 = trainer._pair(tok, prompt, "정답이다", 4096)
    assert s2 == p_len and full[s2:] == a  # 짧으면 그대로
    # 프롬프트가 최소 보존 길이(16)보다 짧은데 답이 너무 길면 — 앞 · 뒤 조각이 겹쳐 같은 토큰이 두 번 들어가면 안 된다
    short = [{"role": "u", "content": "x"}]  # 프롬프트 15토큰
    ids3, s3 = trainer._pair(tok, short, "가" * 100, 64)
    assert ids3[:s3] == trainer._prompt_ids(tok, short) and len(ids3) == 64


def test_logp_sums_only_answer_tokens():
    m = FakeLM(uniform=True)
    ids = list(range(1, 11))
    # 답(위치 6부터 4개)의 로그확률 합만 — 균등 분포라 4 × log(1/V)
    assert trainer._logp(m, ids, 6).item() == pytest.approx(-4 * math.log(V), rel=1e-5)


@pytest.fixture
def fake_base(monkeypatch):
    made = {}

    def load_base(hf_id):
        made["model"], made["tok"] = FakeLM(), FakeTok()
        made["hf_id"] = hf_id
        return made["model"], made["tok"]

    monkeypatch.setattr(trainer, "load_base", load_base)
    monkeypatch.setattr(trainer, "lora", lambda model, r=8, **kw: model)  # LoRA 는 peft 에 맡긴 부분 — 고리만 본다
    return made


def test_sft_masks_prompt_and_saves(fake_base, tmp_path):
    rows = [_row(f"질문 {i}", a=f"답 {i} [1].") for i in range(5)]
    job = FakeJob()
    res = trainer.sft(job, "base-x", rows, tmp_path / "out", accum=2, max_len=512)
    m, tok = fake_base["model"], fake_base["tok"]
    assert res["examples_seen"] == 5 and res["steps"] == 3 and len(res["curve"]) == 3
    for row, labels in zip(rows, m.labels, strict=True):
        ids, start = trainer._pair(tok, row["messages"][:-1], row["messages"][-1]["content"], 512)
        # 손실은 답 부분에만 — 시스템 · 근거 · 질문까지 맞히게 하면 근거를 외우는 쪽으로 배운다
        assert (labels[0, :start] == -100).all() and labels[0, start:].tolist() == ids[start:]
    assert (tmp_path / "out" / "adapter_model.safetensors").exists() and (tmp_path / "out" / "tokenizer.json").exists()
    assert job.updates[-1][0] == 1.0 and "SFT 5/5" in job.updates[-1][1]

    res2 = trainer.sft(FakeJob(), "base-x", rows, tmp_path / "out2", accum=2, max_steps=1)
    assert res2["examples_seen"] == 2 and res2["steps"] == 1  # 걸음 상한 = max_steps × accum 예시


def test_dpo_uses_adapter_off_reference(fake_base, tmp_path):
    p = [{"role": "system", "content": "s"}, {"role": "user", "content": "질문: q"}]
    rows = [{"prompt": p, "chosen": [{"role": "assistant", "content": f"좋은 답 {i} [1]."}], "rejected": [{"role": "assistant", "content": "모름"}]}
            for i in range(3)]  # fmt: skip
    res = trainer.dpo(FakeJob(), "base-x", rows, tmp_path / "dpo", accum=2)
    # 기준 모델 = 어댑터를 끈 같은 모델(쌍마다 한 번) — 모델을 둘 올리지 않으려고
    assert fake_base["model"].adapter_off == 3 and res["pairs_seen"] == 3 and res["steps"] == 2
    assert {"loss_first", "loss_last", "reward_acc_last", "margin_last"} <= set(res)
    # 첫 걸음엔 정책 = 기준이라 여백 0 → 손실 log 2
    assert res["loss_first"] == pytest.approx(math.log(2), abs=0.05)


# ── P6 끝점 ────────────────────────────────────────────────────────────────
def test_local_chat_loads_once_and_decodes(monkeypatch):
    loads = []

    def load_base(hf_id):
        loads.append(hf_id)
        return FakeLM(completions=[[5, 6, 7]]), FakeTok(words={5: "배수 ", 6: "필터 ", 7: "[1]"})

    monkeypatch.setattr(trainer, "load_base", load_base)
    monkeypatch.setattr(local_llm, "_loaded", {"key": None, "model": None, "tok": None})
    msgs = [{"role": "user", "content": "질문"}]
    r = local_llm.chat("base:x", "x", None, "base", msgs, 16, 0.0)
    assert r["text"] == "배수 필터 [1]" and r["completion_tokens"] == 3
    assert r["prompt_tokens"] == len(trainer._prompt_ids(FakeTok(), msgs))  # 학습과 같은 프롬프트 모양으로 생성
    model = local_llm._loaded["model"]
    assert model.gen_kwargs[-1]["do_sample"] is False and model.gen_kwargs[-1]["temperature"] is None  # 온도 0 = 탐욕 생성(재현 가능)
    local_llm.chat("base:x", "x", None, "base", msgs, 16, 0.7)
    assert loads == ["x"] and model.gen_kwargs[-1]["do_sample"] is True  # 같은 키는 다시 올리지 않는다
    local_llm.chat("base:y", "y", None, "base", msgs, 16, 0.0)
    assert loads == ["x", "y"]  # 다른 이름이면 바꿔 올린다(메모리에 하나만)


def test_chat_completions_endpoint(client, monkeypatch):
    seen = []

    def fake_chat(key, base, path, kind, messages, max_tokens, temperature):
        seen.append({"key": key, "base": base, "path": path, "kind": kind, "messages": messages, "max_tokens": max_tokens})
        return {"text": "답", "prompt_tokens": 3, "completion_tokens": 1, "seconds": 0.0}

    monkeypatch.setattr(local_llm, "chat", fake_chat)
    with SessionLocal() as db:
        ms = [AppModel(kind="llm_adapter", name="a", model_hf_id="base-a", method="sft"),
              AppModel(kind="llm_merged", name="m", model_hf_id="base-m", method="merge-linear"),
              AppModel(kind="classifier", name="c", model_hf_id="emb", method="logreg")]  # fmt: skip
        db.add_all(ms)
        db.commit()
        ad, mg, other = (m.id for m in ms)
    try:
        url = "/api/posttrain/v1/chat/completions"
        r = client.post(
            url,
            json={
                "model": "pt-base",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "가"}, {"type": "text", "text": "나"}]}],
            },
        )
        # OpenAI 호환 모양 — LLM 비교 · 레드팀이 다른 LLM 과 같은 코드로 학습한 모델을 부르려고
        assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "답" and r.json()["usage"]["completion_tokens"] == 1
        assert seen[-1]["kind"] == "base" and seen[-1]["base"] == get_settings().posttrain_base_model and seen[-1]["path"] is None
        assert (
            seen[-1]["messages"] == [{"role": "user", "content": "가 나"}] and seen[-1]["max_tokens"] == 512
        )  # 여러 부분 글은 이어 붙인다
        client.post(url, json={"model": f"pt-{ad}", "messages": [{"role": "user", "content": "q"}], "max_completion_tokens": 20})
        assert (
            seen[-1]["kind"] == "adapter"
            and seen[-1]["base"] == "base-a"
            and seen[-1]["path"].name == str(ad)
            and seen[-1]["max_tokens"] == 20
        )
        client.post(url, json={"model": f"pt-{mg}", "messages": [{"role": "user", "content": "q"}]})
        assert seen[-1]["kind"] == "merged" and seen[-1]["key"] == f"m:{mg}"
        # 학습한 LLM 이 아닌 응용 모델 · 없는 번호 · 이상한 이름은 404 — 엉뚱한 가중치를 LLM 으로 올리지 않게
        for bad in (f"pt-{other}", "pt-999999", "pt-abc", "gpt-4"):
            assert client.post(url, json={"model": bad, "messages": [{"role": "user", "content": "q"}]}).status_code == 404
    finally:
        with SessionLocal() as db:
            for i in (ad, mg, other):
                db.delete(db.get(AppModel, i))
            db.commit()


def test_api_validation(client):
    ov = client.get("/api/posttrain/overview").json()
    assert {"base_model", "datasets", "models", "device"} <= set(ov)
    # 없는 데이터 이름은 404(서버 오류 500 이 아니라)
    assert client.post("/api/posttrain/train", json={"name": "x", "dataset": "no_such_set"}).status_code == 404
    name = "pt_test_kind"
    data.save(name, [_row("질문")], {}, "sft")
    try:
        # 데이터 종류와 학습 방법이 다르면 작업을 만들기 전에 거절한다(SFT 데이터로 DPO 를 돌리면 키 오류로 한참 뒤 실패)
        assert client.post("/api/posttrain/train", json={"name": "x", "dataset": name, "method": "dpo"}).status_code == 400
    finally:
        for f in (data.root() / "datasets").glob(f"{name}*"):
            f.unlink()
    assert client.post("/api/posttrain/datasets", json={"name": "empty", "flywheel": False}).status_code == 400  # 남은 예시 없음
    assert client.post("/api/posttrain/merge", json={"name": "m", "adapters": [999999]}).status_code == 400
    assert client.delete("/api/posttrain/models/999999").status_code == 404


def test_evaluate_samples_from_filtered_items(client, rag_collection, scripted_llm):
    # 정답 문서 없는 항목이 섞인 세트: 표본 수를 전체 항목 수로 정하면 sample 이 ValueError(500)였다
    with SessionLocal() as db:
        s = EvalSet(collection_id=rag_collection["cid"], name="섞인 세트", method="manual",
                    items=[{"query": "세탁기 배수가 안 될 때", "doc_ids": [rag_collection["docs"]["AS안내.md"]]}, {"query": "정답 문서 없음"},
                           {"query": "또 없음", "doc_ids": []}])  # fmt: skip
        db.add(s)
        db.commit()
        sid = s.id
    r = client.post("/api/posttrain/evaluate", json={"models": ["fake"], "eval_set_id": sid, "redteam": False})
    assert r.status_code == 202, r.text
    done = wait_job(client, r.json())
    assert done["status"] == "done", done
    assert done["result"]["n_queries"] == 1 and done["result"]["quality"][0]["model"] == "fake"


# ── P7 변환 ────────────────────────────────────────────────────────────────
def test_export_plan_and_run_without_script(monkeypatch, tmp_path):
    st = get_settings()
    monkeypatch.setattr(st, "llm_models_dir", tmp_path / "gguf")
    monkeypatch.setattr(st, "llama_server_bin", tmp_path / "bin" / "llama-server.exe")
    monkeypatch.setattr(st, "llama_convert_script", None)
    p = export.plan(tmp_path / "merged", "pt1-m", "Q5_K_M")
    assert p["f16"] == tmp_path / "gguf" / "pt1-m-f16.gguf" and p["quantized"] == tmp_path / "gguf" / "pt1-m-Q5_K_M.gguf"
    # 양자화 도구는 llama-server 옆에 있다 — 따로 설정하지 않게
    assert p["quantize_bin"].parent == tmp_path / "bin" and p["quantize_bin"].name.startswith("llama-quantize")
    assert "--outtype f16" in p["commands"][0] and p["commands"][1].endswith("Q5_K_M")
    r = export.run(tmp_path / "merged", "pt1-m")
    # 변환 스크립트가 없으면 아무것도 돌리지 않고 할 일(명령)을 보여 준다
    assert r["ok"] is False and "LLAMA_CONVERT_SCRIPT" in r["reason"] and len(r["commands"]) == 2
    monkeypatch.setattr(st, "llm_models_dir", None)
    assert export.plan(tmp_path / "models" / "3", "x")["f16"].parent == tmp_path / "models"  # 폴더 설정이 없으면 모델 옆에


def test_export_run_with_fake_subprocess(monkeypatch, tmp_path):
    st = get_settings()
    script = tmp_path / "convert_hf_to_gguf.py"
    script.write_text("", encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    qbin = bindir / ("llama-quantize.exe" if sys.platform == "win32" else "llama-quantize")
    qbin.write_bytes(b"")
    monkeypatch.setattr(st, "llm_models_dir", tmp_path)
    monkeypatch.setattr(st, "llama_server_bin", bindir / "llama-server.exe")
    monkeypatch.setattr(st, "llama_convert_script", script)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        out = Path(cmd[cmd.index("--outfile") + 1]) if "--outfile" in cmd else Path(cmd[2])
        out.write_bytes(b"0" * 1024)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(export.subprocess, "run", run)
    prog = []
    r = export.run(tmp_path / "merged", "pt2-m", "Q4_0", lambda f, m: prog.append(m))
    assert r["ok"] and [Path(f["path"]).name for f in r["files"]] == ["pt2-m-f16.gguf", "pt2-m-Q4_0.gguf"]
    assert calls[0][0] == sys.executable and calls[1][0] == str(qbin) and [s["step"] for s in r["steps"]] == ["convert", "quantize"]
    assert len(prog) == 2

    monkeypatch.setattr(export.subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="No module named gguf"))
    bad = export.run(tmp_path / "merged", "pt3-m")
    assert bad["ok"] is False and "gguf" in bad["reason"] and "No module named gguf" in bad["steps"][0]["tail"]  # 실패 이유를 남긴다


def test_export_api_requires_merged(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "llama_convert_script", None)
    with SessionLocal() as db:
        ad = AppModel(kind="llm_adapter", name="a", model_hf_id="b", method="sft")
        mg = AppModel(kind="llm_merged", name="합친 모델 v1", model_hf_id="b", method="merge-linear")
        db.add_all([ad, mg])
        db.commit()
        ids = (ad.id, mg.id)
    try:
        # 어댑터만으로는 GGUF 를 만들 수 없다 — 기본 모델에 합친 모델만
        assert client.post("/api/posttrain/export", json={"model_id": ids[0]}).status_code == 400
        r = client.post("/api/posttrain/export", json={"model_id": ids[1], "quant": "Q8_0"}).json()
        # 파일 이름은 번호 + 이름의 글자 · 숫자만(띄어쓰기 · 기호는 명령 인자를 깨뜨린다)
        assert Path(r["plan"]["quantized"]).name == f"pt{ids[1]}-합친모델v1-Q8_0.gguf" and len(r["commands"]) == 2
        done = wait_job(client, r)
        assert done["status"] == "done" and done["result"]["ok"] is False
        with SessionLocal() as db:
            assert db.get(AppModel, ids[1]).metrics["export"]["ok"] is False  # 변환 결과를 모델 기록에 남긴다
    finally:
        with SessionLocal() as db:
            for i in ids:
                db.delete(db.get(AppModel, i))
            db.commit()
        shutil.rmtree(data.root() / "models" / str(ids[1]), ignore_errors=True)
