"""RLVR API (RV1~RV6): 검증 가능한 과제 → 기록 · 재생 환경 → 보상 → GRPO(LoRA) → 학습 외 유형 · 안전성 평가 · 보상 해킹 감시.

학습한 정책은 후학습과 같은 표(AppModel kind=llm_adapter, method=grpo)에 두어 후학습 끝점(/api/posttrain/v1, pt-<번호>)으로 불린다 —
평가 · 레드팀 · 서빙 실측이 같은 주소 모양으로 정책을 부르게. 학습은 관리자만.
"""

import shutil
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.auth import User, require_admin
from app.core.config import get_settings
from app.core.db import AppModel, Collection, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import default_config, run_search
from app.stages.guardrails import redteam
from app.stages.posttrain import data as pt_data
from app.stages.rlvr import env as env_mod
from app.stages.rlvr import policy, reward
from app.stages.rlvr import tasks as tk

router = APIRouter(prefix="/api/rlvr", tags=["rlvr"])
DB = Annotated[Session, Depends(get_db)]


def _search(db: Session, cid: int) -> env_mod.SearchFn:
    cfg = default_config(db, cid, top_k=4)
    if cfg is None:
        raise HTTPException(400, "컬렉션에 준비된 청크 세트가 없습니다")
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    return lambda q: run_search(db, q, cfg)["results"]


def _tasks(name: str) -> dict[str, Any]:
    """과제 묶음 읽기 — 없는 이름이 500(서버 오류)으로 보이지 않게 404 로."""
    try:
        return tk.load(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/overview")
def overview(db: DB) -> dict:
    ms = db.scalars(select(AppModel).where(AppModel.kind == "llm_adapter", AppModel.method == "grpo").order_by(AppModel.id.desc())).all()
    return {"base_model": get_settings().posttrain_base_model, "tasks": tk.listing(), "weights": reward.W,
            "policies": [{"id": m.id, "name": m.name, "base": m.model_hf_id, "endpoint_model": f"pt-{m.id}", "metrics": {k: v for k, v in (m.metrics or {}).items() if k != "log"},
                          "curve": [{k: x.get(k) for k in ("step", "reward", "correct", "chars")} for x in (m.metrics or {}).get("log", [])], "at": m.created_at.isoformat()} for m in ms]}  # fmt: skip


class TasksIn(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    collection_id: int
    graph: str = "legal"
    n_per_type: int = Field(default=30, ge=2, le=500)
    seed: int = 7


@router.post("/tasks")
def build_tasks(body: TasksIn, db: DB) -> dict:
    if db.get(Collection, body.collection_id) is None:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다")
    ts = tk.build(db, body.collection_id, body.graph, body.n_per_type, body.seed)
    if not ts["train"]:
        raise HTTPException(400, f"과제를 만들 자료가 없습니다(법령 문서 · 그래프 '{body.graph}') — {ts['counts']}")
    return tk.save(body.name, ts) | {"examples": (ts["train"] + ts["test"])[:6]}


@router.get("/tasks/{name}")
def get_tasks(name: str) -> dict:
    return _tasks(name)


class ScoreIn(BaseModel):
    tasks: str
    task_id: str
    text: str = Field(max_length=4000)


@router.post("/score")
def score(body: ScoreIn) -> dict:
    ts = _tasks(body.tasks)
    t = next((x for x in ts["train"] + ts["test"] if x["id"] == body.task_id), None)
    if t is None:
        raise HTTPException(404, "과제가 없습니다")
    return reward.score(t, body.text) | {"task": t}


class EnvIn(BaseModel):
    tasks: str
    n: int = Field(default=10, ge=1, le=100)


@router.post("/env/check")
def env_check(body: EnvIn, db: DB) -> dict:
    """환경-실제 차이(RV2): 기록해 둔 도구 결과와 지금 실제 결과의 겹침."""
    ts = _tasks(body.tasks)
    return env_mod.gap_check(body.tasks, _search(db, ts["collection_id"]), db, ts["graph"], (ts["train"] + ts["test"])[: body.n])


class TrainIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    tasks: str
    steps: int = Field(default=30, ge=1, le=2000)
    group: int = Field(default=4, ge=2, le=16)
    lr: float = Field(default=1e-5, gt=0, lt=1)
    beta: float = Field(default=0.02, ge=0, le=1)
    max_new: int = Field(default=96, ge=16, le=512)
    temperature: float = Field(default=0.8, gt=0, le=2)
    r: int = Field(default=8, ge=2, le=64)


@router.post("/train", status_code=202)
def train(body: TrainIn, request: Request, db: DB) -> dict:
    require_admin(request, "GRPO 학습")
    ts = _tasks(body.tasks)
    base = get_settings().posttrain_base_model
    m = AppModel(
        kind="llm_adapter",
        name=body.name,
        model_hf_id=base,
        method="grpo",
        config=body.model_dump() | {"base": base},
        n_train=len(ts["train"]),
    )
    db.add(m)
    db.commit()
    mid = m.id

    def work(job: Job) -> dict[str, Any]:
        out = pt_data.root() / "models" / str(mid)
        with SessionLocal() as sdb:
            env = env_mod.Env(body.tasks, _search(sdb, ts["collection_id"]), sdb, ts["graph"])
            try:
                res = policy.train(job, base, ts["train"], env, out, steps=body.steps, group=body.group, lr=body.lr, beta=body.beta, max_new=body.max_new,
                                   temp=body.temperature, r=body.r)  # fmt: skip
            except Exception:
                shutil.rmtree(out, ignore_errors=True)
                sdb.delete(sdb.get(AppModel, mid))
                sdb.commit()
                raise
            sdb.get(AppModel, mid).metrics = res
            sdb.commit()
        return {"model_id": mid} | {k: v for k, v in res.items() if k != "log"} | {"curve": res["log"][-50:]}

    return jobs.submit("rlvr_train", f"GRPO · {body.name} · {body.steps}걸음", work).to_dict() | {"model_id": mid}


def _cfg(request: Request, model: str) -> llm.LLMConfig:
    if model.startswith("pt-"):
        return llm.LLMConfig("openai", model, str(request.base_url).rstrip("/") + "/api/posttrain/v1", get_settings().api_token, 900)
    return llm.resolve(None, model)


class EvalIn(BaseModel):
    tasks: str
    models: list[str] = Field(min_length=1, max_length=5)  # 첫 번째가 기준 — pt-base · pt-<번호> · 다른 LLM
    splits: list[Literal["train", "test"]] = Field(default_factory=lambda: ["train", "test"])
    max_per_split: int = Field(default=30, ge=1, le=500)
    redteam: bool = True


@router.post("/eval", status_code=202)
def evaluate(body: EvalIn, request: Request, db: DB) -> dict:
    """일반화 · 안전성(RV6): 학습 / 시험(학습 외 유형 포함) 정답률을 유형별로, 같은 공격 문항으로 레드팀 — 그리고 보상 해킹 감시."""
    ts = _tasks(body.tasks)
    cfgs = [_cfg(request, m) for m in body.models]

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        res: dict[str, Any] = {"models": []}
        with SessionLocal() as sdb:
            env = env_mod.Env(body.tasks, _search(sdb, ts["collection_id"]), sdb, ts["graph"])
            items = [(sp, t) for sp in body.splits for t in ts[sp][: body.max_per_split]]
            for mi, c in enumerate(cfgs):
                by: dict[str, list[int]] = {}
                split_acc: dict[str, list[int]] = {}
                rewards, chars = [], []
                for i, (sp, t) in enumerate(items):
                    if i % 5 == 0:
                        job.update((mi * len(items) + i) / (len(cfgs) * len(items)) * 0.85, f"{c.model} · {sp} {i + 1}/{len(items)}")
                    msgs = env_mod.prompt(t, env.observe(t))
                    try:
                        text = llm.chat(c, msgs[0]["content"], msgs[1]["content"], 200, 0.0)["text"]
                    except llm.LLMError as exc:
                        text = f"(오류 {exc})"
                    s = reward.score(t, text)
                    by.setdefault(f"{sp}:{t['type']}", []).append(int(s["correct"]))
                    split_acc.setdefault(sp, []).append(int(s["correct"]))
                    rewards.append(s["reward"])
                    chars.append(s["chars"])
                res["models"].append({"model": c.model, "acc": {k: round(sum(v) / len(v), 3) for k, v in split_acc.items()},
                                      "by_type": {k: {"n": len(v), "acc": round(sum(v) / len(v), 3)} for k, v in sorted(by.items())},
                                      "mean_reward": round(sum(rewards) / len(rewards), 3) if rewards else None, "mean_chars": round(sum(chars) / len(chars), 1) if chars else None})  # fmt: skip
            env.save()
            if len(res["models"]) >= 2:
                a, b = res["models"][0]["acc"], res["models"][-1]["acc"]
                res["hacking"] = reward.hacking([], [a.get("train", 0), b.get("train", 0)], [a.get("test", 0), b.get("test", 0)])
            if body.redteam:
                col, cs = redteam.ensure_collection(sdb)
                rcfg = {"mode": "bm25", "chunk_set_id": cs.id, "top_k": 4}
                res["safety"] = []
                for c in cfgs:

                    def answer_fn(q: str, groups: list[str], c: llm.LLMConfig = c) -> dict[str, Any]:
                        return serve.answer_once(
                            sdb,
                            q,
                            rcfg | {"acl_groups": groups},
                            c,
                            user=User("redteam", tuple(groups), "user"),
                            max_tokens=300,
                            kind="redteam",
                        )

                    job.update(0.9, f"레드팀 · {c.model}")
                    res["safety"].append({"model": c.model, "summary": redteam.run(sdb, col.id, answer_fn, None)["summary"]})
            res |= {"tasks": body.tasks, "seconds": round(time.perf_counter() - t0, 1)}
            res["run_id"] = crud.record_run(
                sdb, "rlvr_eval", body.models, f"RLVR 평가 · {body.tasks}", body.model_dump(), res, res["seconds"] * 1000
            ).id
        return res

    return jobs.submit("rlvr_eval", f"RLVR 평가 · {body.tasks} · {len(cfgs)}개 모델", work).to_dict()
