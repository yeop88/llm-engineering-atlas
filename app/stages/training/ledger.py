"""TL1~TL8 학습 생애주기 원장: 학습한 모델 하나를 '어떤 데이터로 · 어떤 순서로 · 무엇을 확인하고' 만들었는지 한 줄로 잇는다.

후학습(P) · RLVR(RV) · 플라이휠(FW) 기록은 각자 남는다. 데이터 메타는 data/posttrain/datasets, 모델은 AppModel, 평가는 TestRun(pt_eval ·
rlvr_eval), 배포는 FwVersion 에 있다. 그래서 모델 하나에서 시작해 거꾸로 따라간다. 병합 모델은 어댑터들로, DPO 어댑터는 시작 SFT 어댑터로,
어댑터는 데이터로, 데이터는 출처 · 거르기 보고로, 기본 모델은 계보 기록으로 이어진다. 단계마다 '했다 · 안 했다 · 확인 필요'를 표시한다.
빈칸을 메우지 않고 빈칸이라고 보여 주는 것이 목적이다. 누수 검사를 안 한 데이터, 레드팀 없이 나간 모델이 보이게 하려는 것이다.
"""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import AppModel, FwVersion, TestRun
from app.stages.lineage import inspect as lineage
from app.stages.posttrain import data as pt_data

KINDS = ("llm_adapter", "llm_merged")


def chain(db: Session, mid: int) -> list[AppModel]:
    """이 모델을 만든 모델들(자기 포함, 먼저 만든 것부터). 병합은 어댑터 전부, DPO · GRPO 는 시작 어댑터를 따라간다."""
    seen: dict[int, AppModel] = {}

    def walk(i: int) -> None:
        m = db.get(AppModel, i)
        if m is None or m.id in seen or m.kind not in KINDS:
            return
        cfg = m.config or {}
        for a in cfg.get("adapters") or []:
            walk(int(a))
        if cfg.get("init_adapter_id"):
            walk(int(cfg["init_adapter_id"]))
        seen[m.id] = m

    walk(mid)
    return sorted(seen.values(), key=lambda m: m.id)


def _dataset_meta(name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    p = pt_data.root() / "datasets" / f"{name}.meta.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except ValueError:
        return None


def _runs(db: Session, kinds: tuple[str, ...], endpoint: str) -> list[TestRun]:
    # 평가 기록의 models 는 'pt-<번호>' 같은 끝점 이름 — 이 모델이 들어간 실행만
    rows = db.scalars(select(TestRun).where(TestRun.kind.in_(kinds)).order_by(TestRun.id.desc()).limit(200)).all()
    return [r for r in rows if endpoint in (r.model_hf_ids or [])]


def _pick(items: list[dict[str, Any]], model: str) -> dict[str, Any] | None:
    return next((x for x in items or [] if x.get("model") == model), None)


def _step(
    no: str, title: str, state: str, facts: list[str], warn: list[str] | None = None, links: list[str] | None = None
) -> dict[str, Any]:
    # state: done(했다) · missing(안 했다) · skipped(이 앱에서 하지 않는 단계) · check(했지만 확인 필요)
    return {
        "no": no,
        "title": title,
        "state": "check" if state == "done" and warn else state,
        "facts": facts,
        "warnings": warn or [],
        "links": links or [],
    }


def lifecycle(db: Session, mid: int, data_dir: Path) -> dict[str, Any]:
    ms = chain(db, mid)
    if not ms:
        raise ValueError("학습한 모델이 아닙니다")
    top = ms[-1]
    ep = f"pt-{top.id}"
    trains = [m for m in ms if m.method in ("sft", "dpo", "grpo")]
    names = [m.config.get("dataset") for m in trains if (m.config or {}).get("dataset")]
    metas = [(n, _dataset_meta(n)) for n in dict.fromkeys(names)]
    steps = []

    # TL1 수집 — 출처별 건수
    facts, warn = [], []
    for n, meta in metas:
        if meta is None:
            warn.append(f"데이터 '{n}' 의 메타가 없음(지워졌거나 밖에서 만듦) — 출처를 알 수 없다")
            continue
        by = (meta.get("report") or {}).get("by_source") or {}
        facts.append(f"{n} ({meta.get('kind')}) {meta.get('n')}건 — " + (" · ".join(f"{k} {v}" for k, v in by.items()) or "출처 기록 없음"))
    if any(m.method == "grpo" for m in trains):
        facts += [f"GRPO 과제 '{m.config.get('tasks')}' 학습 {m.n_train}개" for m in trains if m.method == "grpo"]
    steps.append(_step("TL1", "데이터 수집", "done" if facts else "missing", facts, warn, ["/posttrain/data#select"]))

    # TL2 거르기 — 형식 → 중복 → 누수, 누수 검사에 쓴 평가 세트
    facts, warn = [], []
    for n, meta in metas:
        rep = (meta or {}).get("report") or {}
        if not rep:
            continue
        facts.append(
            f"{n}: 입력 {rep.get('in')} → 형식 {rep.get('format_ok')} → 중복 제거 {rep.get('dedup')} → 누수 제거 {rep.get('no_leak')}"
        )
        if not rep.get("exclude_sets"):
            warn.append(f"{n}: 누수 검사에 쓴 평가 세트가 없음 — 학습 전후 평가가 외운 질문일 수 있다")
        elif rep.get("leaked_examples"):
            facts.append(f"{n}: 평가와 겹쳐 뺀 예 {len(rep['leaked_examples'])}건 이상(예: {rep['leaked_examples'][0][:40]})")
    steps.append(_step("TL2", "전처리 · 중복 제거", "done" if facts else "missing", facts, warn, ["/training/lifecycle#audit"]))

    # TL3 사전학습 — 하지 않음. 기본 모델의 계보 기록만
    base = (ms[0].config or {}).get("base") or ms[0].model_hf_id
    fam, org, _ = lineage.family(base or "")
    rec = lineage.load(data_dir).get(f"hf:{base}")
    facts = [f"기본 모델 {base} · {fam}{f' ({org})' if org else ''}"]
    warn = []
    if rec:
        lic = rec.get("license") or {}
        bases = ", ".join(b["name"] for b in rec.get("base_models") or [])
        facts.append(f"계보 기록: 라이선스 {lic.get('id') or lic.get('name') or '-'} · 파라미터 {rec.get('params_b')}B · 학습 맥락 {(rec.get('context') or {}).get('trained')}"
                     + (f" · 기반 {bases}" if bases else ""))  # fmt: skip
        if lic.get("check"):
            warn.append("라이선스 확인 필요 — 계보 맵(LN5)")
    else:
        warn.append("계보 맵에 기록이 없음 — 기본 모델의 라이선스 · 사전학습 정보를 확인하지 않음")
    steps.append(_step("TL3", "사전학습(기록만)", "done", facts, warn, ["/lineage/models"]))

    # TL4 지시 튜닝 · TL5 선호 정렬 — 학습 기록
    def train_facts(methods: tuple[str, ...]) -> list[str]:
        out = []
        for m in trains:
            if m.method not in methods:
                continue
            met = m.metrics or {}
            loss = met.get("final_loss") or met.get("loss") or (met.get("losses") or [None])[-1]
            out.append(f"#{m.id} {m.name} · {m.method.upper()} · {m.n_train}건" + (f" · 마지막 손실 {round(loss, 4)}" if isinstance(loss, int | float) else "")
                       + (f" · 시작 #{m.config['init_adapter_id']}" if (m.config or {}).get("init_adapter_id") else ""))  # fmt: skip
        return out

    sft = train_facts(("sft",))
    steps.append(_step("TL4", "지시 튜닝", "done" if sft else "missing", sft, [], ["/posttrain/train"]))
    pref = train_facts(("dpo", "grpo"))
    steps.append(_step("TL5", "선호 정렬", "done" if pref else "missing", pref, [], ["/posttrain/train", "/rlvr/train"]))
    merges = [m for m in ms if (m.method or "").startswith("merge")]

    # TL6 안전 · TL7 평가 — 이 모델이 들어간 평가 실행, 첫 모델(기준) 대비
    evals = _runs(db, ("pt_eval", "rlvr_eval"), ep)
    safety, quality, warn6, warn7 = [], [], [], []
    for r in evals:
        res = r.result or {}
        first = (r.model_hf_ids or [None])[0]
        s, s0 = _pick(res.get("safety"), ep), _pick(res.get("safety"), first)
        if s:
            a, b = s["summary"].get("attack_pass_rate"), s["summary"].get("benign_pass_rate")
            line = f"run #{r.id}: 공격 막음 {a} · 정상 통과 {b}"
            if s0 and s0 is not s:
                a0, b0 = s0["summary"].get("attack_pass_rate"), s0["summary"].get("benign_pass_rate")
                line += f" (기준 {first}: {a0} · {b0})"
                if a is not None and a0 is not None and a < a0:
                    warn6.append(f"run #{r.id}: 학습 뒤 공격을 덜 막음({a0} → {a})")
                if b is not None and b0 is not None and b < b0 - 0.1:
                    warn6.append(f"run #{r.id}: 정상 질문 거절이 늘어남({b0} → {b})")
            safety.append(line)
        if r.kind == "pt_eval":
            q = _pick(res.get("quality"), ep)
            if q and q.get("summary"):
                sm = q["summary"]
                line = f"run #{r.id} {res.get('eval_set', {}).get('name', '')}: 품질 {sm.get('quality')} · 거절 정확 {sm.get('correct_refusal')}"
                vs = q.get("vs_first") or {}
                if vs.get("against") and vs.get("against") != ep:
                    line += f" · 기준 대비 {vs.get('diff')} (p={vs.get('p')})"
                    if isinstance(vs.get("diff"), int | float) and vs["diff"] < 0:
                        warn7.append(f"run #{r.id}: 기준 모델보다 품질이 낮음")
                quality.append(line)
        else:
            mm = _pick(res.get("models"), ep)
            if mm:
                quality.append(f"run #{r.id} 과제 {res.get('tasks')}: 정확도 {mm.get('acc')}")
            if res.get("hacking", {}).get("flag"):
                warn7.append(f"run #{r.id}: 보상 해킹 의심 — 학습 과제만 오르고 시험 과제는 그대로")
    if evals and not safety:
        warn6.append("평가는 했지만 레드팀을 끈 채로 — 안전성 확인 없음")
    steps.append(_step("TL6", "안전 정렬 확인", "done" if safety else "missing", safety, warn6, ["/posttrain/eval"]))
    steps.append(_step("TL7", "평가", "done" if quality else "missing", quality, warn7, ["/posttrain/eval", "/rlvr/eval"]))

    # TL8 배포 — 병합 · GGUF · 플라이휠 판
    facts, warn = [], []
    facts += [f"병합 #{m.id} {m.name} ({m.method})" for m in merges]
    exp = (top.metrics or {}).get("export")
    if exp:
        facts.append(f"GGUF {exp.get('quant') or ''} {exp.get('path') or exp.get('gguf') or ''}".strip())
    vers = [v for v in db.scalars(select(FwVersion)).all() if ep in str(v.config or {})]
    facts += [f"플라이휠 판 #{v.id} {v.name} · {v.status}" for v in vers]
    if (exp or vers) and not quality:
        warn.append("평가 기록 없이 내보냄")
    steps.append(_step("TL8", "배포", "done" if (exp or vers) else "missing", facts, warn, ["/posttrain/eval#export", "/flywheel/release"]))

    states = [s["state"] for s in steps]
    return {"model": {"id": top.id, "name": top.name, "kind": top.kind, "method": top.method, "endpoint": ep, "base": base},
            "chain": [{"id": m.id, "name": m.name, "method": m.method, "kind": m.kind, "n_train": m.n_train} for m in ms],
            "steps": steps, "done": states.count("done"), "check": states.count("check"), "missing": states.count("missing")}  # fmt: skip


def models(db: Session) -> list[dict[str, Any]]:
    ms = db.scalars(select(AppModel).where(AppModel.kind.in_(KINDS)).order_by(AppModel.id.desc())).all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "kind": m.kind,
            "method": m.method,
            "base": m.model_hf_id,
            "n_train": m.n_train,
            "at": m.created_at.isoformat(),
        }
        for m in ms
    ]
