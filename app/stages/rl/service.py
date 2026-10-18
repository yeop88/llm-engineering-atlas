"""Best-of-N(보상으로 고르기) · 선호 쌍 수집 · DPO 데이터 내보내기.

설계 이유
- 이 PC 에서 LLM 가중치를 강화학습(PPO · GRPO) · 선호 학습(DPO)으로 직접 고치는 것은 현실적이지 않다(CPU · 내장 GPU).
  그래서 같은 보상 함수로 할 수 있는 두 가지를 한다:
  1) 추론 시점 최적화(Best-of-N): 답을 여러 개 만들어 보상이 가장 높은 것을 고른다 — 학습 없이 보상의 효과를 바로 잴 수 있고,
     '학습하면 얼마나 좋아질 수 있나'의 대략적인 상한이 된다. 대신 비용이 N 배.
  2) 학습 데이터: 같은 질문 · 같은 근거의 좋은 답 / 나쁜 답 쌍을 모아 DPO 형식으로 내보낸다(학습은 GPU 환경의 TRL 등에서).
- 후보 0 은 평소처럼 낮은 온도로 만든다. 그래서 Best-of-N 은 보상 기준으로 평소 답보다 나빠질 수 없고, 비교 기준(평소 답)이
  같은 실행 안에 함께 있어 짝지어 비교할 수 있다.
- 자동 선호 쌍은 보상 차가 충분히 클 때만 저장한다(margin). 차이가 작은 쌍은 보상 함수의 잡음일 가능성이 커 학습을 흐린다.
"""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core import llm, stats
from app.core.db import PreferencePair
from app.core.jobs import Job
from app.stages.rag import answer
from app.stages.rl.reward import reward


def candidates(cfg: llm.LLMConfig, question: str, results: list[dict[str, Any]], n: int, temperature: float, evidence: str = "",
               max_chars: int = 6000, max_tokens: int = 500) -> dict[str, Any]:  # fmt: skip
    context, sources = answer.build_context(results, max_chars)
    cands = []
    for i in range(n):
        t = 0.1 if i == 0 else temperature  # 후보 0 = 평소 답
        res = llm.chat(cfg, answer.SYSTEM, answer.user_prompt(question, context), max_tokens=max_tokens, temperature=t)
        r = reward(res["text"], sources, evidence)
        cands.append({"text": res["text"], "temperature": t, "reward": r["total"], "parts": r["parts"], "seconds": res["seconds"],
                      "refused": r["check"]["refused"], "supported_ratio": r["check"]["supported_ratio"],
                      "cited": r["check"]["cited_sources"]})  # fmt: skip
    best = max(range(n), key=lambda i: (cands[i]["reward"], -i))  # 동점이면 평소 답(앞 번호)
    worst = min(range(n), key=lambda i: cands[i]["reward"])
    return {"context": context, "sources": sources, "candidates": cands, "best": best, "worst": worst}


def save_pair(db: Session, collection_id: int | None, question: str, context: str, chosen: dict[str, Any], rejected: dict[str, Any],
              source: str, meta: dict[str, Any] | None = None) -> PreferencePair:  # fmt: skip
    p = PreferencePair(collection_id=collection_id, question=question, context=context, chosen=chosen["text"], rejected=rejected["text"],
                       chosen_reward=chosen.get("reward"), rejected_reward=rejected.get("reward"), source=source, meta=meta or {})  # fmt: skip
    db.add(p)
    db.commit()
    return p


def _metric(c: dict[str, Any], evidence: str, sources: list[dict[str, Any]]) -> float:
    """비교용 품질: 정답 근거 인용(근거 문장을 알면) 아니면 문장 근거율 — 다른 단계 평가와 같은 기준."""
    if evidence:
        return float(c["parts"].get("evidence_cited", 0.0) > 0)
    return float(c["supported_ratio"] or 0.0)


def evaluate(db: Session, job: Job, items: list[dict[str, Any]], search_fn, cfg: llm.LLMConfig, n: int, temperature: float,
             margin: float, collection_id: int | None, collect: bool) -> dict[str, Any]:  # fmt: skip
    rows = []
    saved = 0
    for qi, it in enumerate(items):
        job.update(qi / len(items) * 0.97, f"질문 {qi + 1}/{len(items)} · 후보 {n}개")
        res = candidates(cfg, it["query"], search_fn(it["query"]), n, temperature, it.get("evidence", ""))
        c = res["candidates"]
        g, b, w = c[0], c[res["best"]], c[res["worst"]]
        rows.append({"query": it["query"], "greedy_reward": g["reward"], "best_reward": b["reward"], "worst_reward": w["reward"],
                     "greedy_q": _metric(g, it.get("evidence", ""), res["sources"]), "best_q": _metric(b, it.get("evidence", ""), res["sources"]),
                     "picked": res["best"], "seconds": sum(x["seconds"] for x in c), "greedy_seconds": g["seconds"],
                     "best_text": b["text"][:400], "greedy_text": g["text"][:400]})  # fmt: skip
        if collect and b["reward"] - w["reward"] >= margin:
            save_pair(
                db,
                collection_id,
                it["query"],
                res["context"],
                b,
                w,
                "auto",
                {"reward_gap": round(b["reward"] - w["reward"], 4), "model": cfg.model},
            )
            saved += 1
    gq, bq = [r["greedy_q"] for r in rows], [r["best_q"] for r in rows]
    gr, br = [r["greedy_reward"] for r in rows], [r["best_reward"] for r in rows]
    return {
        "n_queries": len(rows), "n": n, "temperature": temperature, "llm": cfg.public(),
        "greedy": {"quality": round(sum(gq) / len(gq), 4), "reward": round(sum(gr) / len(gr), 4), "seconds": round(sum(r["greedy_seconds"] for r in rows) / len(rows), 1)},
        "best_of_n": {"quality": round(sum(bq) / len(bq), 4), "reward": round(sum(br) / len(br), 4), "seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1)},
        "quality_paired": stats.paired_mean(bq, gq), "reward_paired": stats.paired_mean(br, gr),
        "changed": sum(r["picked"] != 0 for r in rows), "pairs_saved": saved, "rows": rows,
    }  # fmt: skip


def dpo_jsonl(pairs: list[PreferencePair]) -> str:
    """TRL 등 선호 학습 도구가 읽는 대화형 선호 형식: prompt(시스템 + 근거 · 질문) · chosen · rejected."""
    lines = []
    for p in pairs:
        prompt = [{"role": "system", "content": answer.SYSTEM}, {"role": "user", "content": answer.user_prompt(p.question, p.context)}]
        lines.append(json.dumps({"prompt": prompt, "chosen": [{"role": "assistant", "content": p.chosen}],
                                 "rejected": [{"role": "assistant", "content": p.rejected}],
                                 "meta": {"source": p.source, "chosen_reward": p.chosen_reward, "rejected_reward": p.rejected_reward}},
                                ensure_ascii=False))  # fmt: skip
    return "\n".join(lines) + ("\n" if lines else "")
