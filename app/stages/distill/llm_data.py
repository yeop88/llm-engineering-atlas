"""LLM 증류 데이터: 교사 LLM 이 검색 근거로 답한 것 중 검증을 통과한 답만 모아, 작은 LLM 을 학습할 대화 데이터(JSONL)로 만든다.

설계 이유
- 작은 LLM 을 CPU 에서 직접 학습시키는 것은 현실적이지 않아(수 시간~수 일), 이 앱은 '좋은 학습 데이터'까지 만들고
  학습은 GPU 환경의 SFT 도구(TRL · Unsloth · LLaMA-Factory 등)에 맡긴다. 형식은 그 도구들이 공통으로 읽는 OpenAI 대화 형식.
- 학생이 실제 서비스에서 받을 입력과 똑같이 만든다: 시스템 지시 + (근거 번호가 붙은 검색 결과 + 질문). 그래야 학생이
  '근거를 인용하며 답하기'라는 행동 자체를 배운다(답만 외우는 것이 아니라).
- 교사의 답이라도 근거에 없는 말을 하면 그 버릇까지 배우므로, 문장 근거율 · 잘못된 인용 · 거절로 거른다(품질 필터).
- 질문은 평가 세트를 쓰지 않는다 — 평가 세트로 학습 데이터를 만들면 나중에 그 평가 세트로 학생을 재는 것이 무의미해진다.
  컬렉션 지문에서 LLM 으로 새 질문을 만들고, 평가 세트 근거가 든 지문은 뺀다(파인튜닝과 같은 누수 방지).
"""

import json
import time
from pathlib import Path
from typing import Any

from app.core import llm
from app.core.config import get_settings
from app.core.jobs import Job
from app.stages.rag import answer


def data_dir() -> Path:
    d = get_settings().data_dir / "distill"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sample(question: str, context: str, text: str) -> dict[str, Any]:
    return {"messages": [{"role": "system", "content": answer.SYSTEM},
                         {"role": "user", "content": answer.user_prompt(question, context)},
                         {"role": "assistant", "content": text}]}  # fmt: skip


def build(job: Job, teacher: llm.LLMConfig, questions: list[str], search_fn, max_chars: int, max_tokens: int, min_support: float,
          name: str) -> dict[str, Any]:  # fmt: skip
    """questions 마다 검색 → 교사 답변 → 검증 → 통과한 것만 저장. search_fn(question) → 검색 결과 목록."""
    kept, dropped = [], {"refused": 0, "low_support": 0, "invalid_citation": 0, "error": 0}
    started = time.perf_counter()
    for i, q in enumerate(questions):
        job.update(i / max(1, len(questions)), f"교사 답변 {i + 1}/{len(questions)}")
        try:
            context, sources = answer.build_context(search_fn(q), max_chars)
            res = llm.chat(teacher, answer.SYSTEM, answer.user_prompt(q, context), max_tokens=max_tokens, temperature=0.1)
        except llm.LLMError:
            dropped["error"] += 1
            continue
        check = answer.verify_lexical(res["text"], sources)
        if check["refused"]:
            dropped["refused"] += 1
        elif check["invalid_citations"]:
            dropped["invalid_citation"] += 1
        elif (check["supported_ratio"] or 0) < min_support:
            dropped["low_support"] += 1
        else:
            kept.append(sample(q, context, res["text"]) | {"meta": {"supported_ratio": check["supported_ratio"], "teacher": teacher.model}})
    path = data_dir() / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for s in kept:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return {"file": path.name, "kept": len(kept), "asked": len(questions), "dropped": dropped, "teacher": teacher.public(),
            "min_support": min_support, "seconds": round(time.perf_counter() - started, 1)}  # fmt: skip


def list_files() -> list[dict[str, Any]]:
    out = []
    for p in sorted(data_dir().glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True):
        with p.open(encoding="utf-8") as f:
            n = sum(1 for _ in f)
        out.append({"name": p.name, "samples": n, "kb": round(p.stat().st_size / 1024, 1)})
    return out


def file_path(name: str) -> Path:
    """다운로드할 파일 경로. 이름에 경로 문자가 있으면 거부한다(폴더 밖 파일을 내주지 않게)."""
    if "/" in name or "\\" in name or ".." in name or not name.endswith(".jsonl"):
        raise ValueError("잘못된 파일 이름입니다.")
    p = data_dir() / name
    if not p.is_file():
        raise FileNotFoundError(name)
    return p
