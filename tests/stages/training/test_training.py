"""학습 생애주기(TL1~TL8): 모델 → 어댑터 → 데이터 → 평가 · 배포 기록을 거꾸로 잇는 원장, 학습 데이터 감사, API.

학습은 하지 않는다. 후학습 맵이 남기는 기록(응용 모델 표의 어댑터 · 병합 행, 데이터 메타 파일, pt_eval 실행)을 직접 만들어 넣고,
원장이 '했다 · 확인 필요 · 안 했다'를 맞게 가르는지 본다 — 원장의 목적은 빈칸(누수 검사 없는 데이터 · 레드팀 없는 평가)을
드러내는 것이라, 경고가 나와야 할 곳에서 나오는지가 핵심이다.
"""

import pytest

from app.core import crud
from app.core.config import get_settings
from app.core.db import AppModel, SessionLocal
from app.stages.posttrain import data as pt_data
from app.stages.training import audit, ledger


def _row(q: str, a: str) -> dict:
    return {"messages": [{"role": "user", "content": f"질문: {q}"}, {"role": "assistant", "content": a}]}


@pytest.fixture
def lineage_chain(client):
    """SFT(누수 검사 없는 데이터) → DPO(시작 = SFT) → 병합. 평가는 병합 모델이 기준(pt-base)보다 품질 · 공격 막음이 낮게."""
    pt_data.save(
        "tl_sft",
        [_row("E4 는?", "배수 필터를 청소하세요.")] * 3,
        {"in": 5, "format_ok": 4, "dedup": 3, "no_leak": 3, "by_source": {"distill": 3}, "exclude_sets": []},
        "sft",
    )
    with SessionLocal() as db:
        sft = AppModel(kind="llm_adapter", name="sft", model_hf_id="Qwen/Qwen3-0.6B", method="sft", config={"dataset": "tl_sft", "base": "Qwen/Qwen3-0.6B"},
                       metrics={"final_loss": 1.2345}, n_train=3)  # fmt: skip
        db.add(sft)
        db.commit()
        dpo = AppModel(
            kind="llm_adapter",
            name="dpo",
            model_hf_id="Qwen/Qwen3-0.6B",
            method="dpo",
            config={"dataset": "tl_gone", "init_adapter_id": sft.id},
            n_train=2,
        )
        db.add(dpo)
        db.commit()
        merged = AppModel(kind="llm_merged", name="merged", model_hf_id="Qwen/Qwen3-0.6B", method="merge-linear", config={"adapters": [dpo.id]},
                          metrics={"export": {"quant": "Q4_0", "path": "pt.gguf"}}, n_train=5)  # fmt: skip
        db.add(merged)
        db.commit()
        ep = f"pt-{merged.id}"
        res = {"eval_set": {"name": "시험"}, "quality": [{"model": "pt-base", "summary": {"quality": 0.6}},
               {"model": ep, "summary": {"quality": 0.5, "correct_refusal": 0.8}, "vs_first": {"against": "pt-base", "diff": -0.1, "p": 0.2}}],
               "safety": [{"model": "pt-base", "summary": {"attack_pass_rate": 0.9, "benign_pass_rate": 0.9}},
                          {"model": ep, "summary": {"attack_pass_rate": 0.7, "benign_pass_rate": 0.9}}]}  # fmt: skip
        crud.record_run(db, "pt_eval", ["pt-base", ep], "후학습 전후", {}, res, 10)
        return {"sft": sft.id, "dpo": dpo.id, "merged": merged.id}


def test_chain_follows_merge_and_init(lineage_chain):
    with SessionLocal() as db:
        ids = [m.id for m in ledger.chain(db, lineage_chain["merged"])]
    assert ids == [lineage_chain["sft"], lineage_chain["dpo"], lineage_chain["merged"]]


def test_lifecycle_flags_gaps(lineage_chain):
    with SessionLocal() as db:
        r = ledger.lifecycle(db, lineage_chain["merged"], get_settings().data_dir)
    st = {s["no"]: s for s in r["steps"]}
    # 데이터 메타가 없는 DPO 데이터 → 출처를 모름(확인 필요)
    assert st["TL1"]["state"] == "check" and any("tl_gone" in w for w in st["TL1"]["warnings"])
    # 누수 검사 세트 없이 만든 데이터 → 경고
    assert any("누수 검사" in w for w in st["TL2"]["warnings"])
    assert st["TL3"]["state"] == "check"  # 계보 맵 기록이 없음
    assert st["TL4"]["state"] == "done" and "1.2345" in st["TL4"]["facts"][0]
    assert st["TL5"]["state"] == "done"
    # 기준보다 공격을 덜 막고 품질이 낮음 → 안전 · 평가 모두 확인 필요
    assert st["TL6"]["state"] == "check" and st["TL7"]["state"] == "check"
    assert st["TL8"]["state"] == "done" and any("GGUF" in f for f in st["TL8"]["facts"])


def test_audit_finds_known_issues():
    rows = [_row(f"세탁기 E4 오류 {i}번", "근거에서 찾을 수 없습니다") for i in range(4)] + [
        _row("필터 위치", "앞면 아래 <|im_end|> 덮개 안")
    ]
    pt_data.save("tl_bad", rows, {}, "sft")
    a = audit.audit("tl_bad")
    assert a["kind"] == "sft" and a["same_answer"]["rows"] == 4 and a["refusal_share"] == 0.8 and a["template_leak"]["n"] == 1
    w = " ".join(a["warnings"])
    assert "같은 답" in w and "거절" in w and "채팅 틀" in w
    pairs = [
        {"prompt": [{"role": "user", "content": f"질문: q{i}"}], "chosen": "길고 자세한 좋은 답입니다", "rejected": "짧음"}
        for i in range(5)
    ]
    pt_data.save("tl_dpo", pairs, {}, "dpo")
    d = audit.audit("tl_dpo")
    # 고른 답이 늘 더 길면 DPO 가 내용보다 길이를 배운다 — 길이 치우침 경고
    assert d["kind"] == "dpo" and d["chosen_longer_share"] == 1.0 and any("길이" in x for x in d["warnings"])


def test_api(client, lineage_chain):
    ms = client.get("/api/training/models").json()
    assert {m["id"] for m in ms["models"]} >= set(lineage_chain.values()) and any(d["name"] == "tl_sft" for d in ms["datasets"])
    r = client.get(f"/api/training/lifecycle/{lineage_chain['merged']}").json()
    assert r["model"]["endpoint"] == f"pt-{lineage_chain['merged']}" and len(r["steps"]) == 8
    assert client.get("/api/training/lifecycle/999999").status_code == 404
    assert client.get("/api/training/datasets/tl_sft/audit").json()["n"] == 3
    assert client.get("/api/training/datasets/nope_x/audit").status_code == 404
    assert client.get("/api/training/datasets/bad%20name/audit").status_code == 422
    assert client.get("/training/lifecycle").status_code == 200
