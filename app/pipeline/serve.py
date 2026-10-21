"""서비스 답변(연결 계층): 2 RAG 답변에 보안 · 가드레일과 요청 기록(평가 · 관측)을 끼운다.

  질문 ─ G1 입력 방어 ─ 검색(G3 권한 · D6 메타 필터는 run_search 가) ─ G1 근거 속 지시 검사 · 격리 ─ LLM 답변
       ─ 2 RAG 검증(근거 일치 · 질문 관련성 · 번호 검사) ─ G4 출력 정책 · G2 개인정보 가리기 ─ 요청 기록(E3 · G5)

답변 화면(스트리밍) · AS 상담 · 레드팀 · A/B 실험이 모두 prepare / finish 를 거치게 해서, 어느 화면에서 묻든 같은 방어와 같은 기록이
남게 한다(화면마다 따로 붙이면 한 곳만 빠져도 그 길로 새어 나간다). 단계 내부 로직(rag · guardrails)은 서로를 모르고 여기서 잇는다.

GUARD_MODE: off = 검사 · 기록만(답은 그대로), mask = 개인정보만 가림(기본), enforce = 인젝션 질문 차단 · 근거 속 지시 문장 빼기 · 정책 위반 수정 · 거절.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core import llm, tracing
from app.core.auth import LOCAL, User
from app.core.config import get_settings
from app.core.db import Collection
from app.pipeline.search import collection_of, run_search
from app.stages.guardrails import injection, pii, policy
from app.stages.rag import answer, legal

KEEP = ("rank", "chunk_id", "document_id", "filename", "title", "page", "heading", "text", "score", "media")


@dataclass
class Prepared:
    question: str
    search_cfg: dict[str, Any]
    mode: str
    user: User
    domain: str = "general"
    collection_id: int | None = None
    tracer: tracing.Tracer = field(default_factory=tracing.Tracer)
    results: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    context: str = ""
    system: str = answer.SYSTEM
    prompt: str = ""
    images: list[bytes] = field(default_factory=list)
    guard: dict[str, Any] = field(default_factory=dict)
    signals: dict[str, Any] = field(default_factory=dict)
    blocked: str | None = None  # LLM 을 부르지 않고 내보낼 글
    block_reason: str = ""  # injection(입력 방어로 차단) | no_sources(근거 없음 — 차단이 아니라 거절)
    search_meta: dict[str, Any] = field(default_factory=dict)
    # 문장 관련성 검사를 할지. 번호 단계 조치 안내('전원 플러그를 뽑습니다')는 질문과 의미가 멀어 늘 '관련 없음'이 되므로(실측 0.43~0.56,
    # 기준 0.68) 그런 답은 부르는 쪽(AS: 오류 코드 일치)이 따로 판정하고 여기서는 끈다
    relevance: bool = True

    def public_sources(self) -> list[dict[str, Any]]:
        return [{k: s.get(k) for k in KEEP} for s in self.sources]


def guard_mode(requested: str | None = None) -> str:
    mode = requested or get_settings().guard_mode
    return mode if mode in ("off", "mask", "enforce") else "mask"


def prepare(
    db: Session,
    question: str,
    search_cfg: dict[str, Any],
    *,
    user: User = LOCAL,
    mode: str | None = None,
    compress_keep: int | None = None,
    max_context_chars: int = 6000,
    images: bool = False,
    max_images: int = 3,
    instruction: str = "",
    relevance: bool = True,
) -> Prepared:
    """LLM 을 부르기 전까지: 입력 방어 → 검색 → 근거 검사 · 격리 → 프롬프트."""
    p = Prepared(question=question, search_cfg=search_cfg, mode=guard_mode(mode), user=user, relevance=relevance)
    p.collection_id = collection_of(db, search_cfg)
    col = db.get(Collection, p.collection_id) if p.collection_id else None
    p.domain = policy.domain_of(col.domain if col else None)
    with p.tracer.step("guard_input"):
        inj = injection.detect(question)
        p.guard["input"] = inj
    if inj["suspicious"] and p.mode == "enforce":
        p.blocked, p.block_reason = injection.BLOCKED_REPLY, "injection"
        return p
    with p.tracer.step("search") as st:
        res = run_search(db, question, search_cfg)
        st["n"] = len(res["results"])
    p.results = res["results"]
    p.search_meta = {k: res.get(k) for k in ("timings_ms", "enhance", "restricted") if res.get(k)}
    if res.get("restricted"):
        p.guard["restricted"] = res["restricted"]
    p.signals = tracing.signals_of(p.results)
    if search_cfg.get("_version"):  # 플라이휠 배포(FW7): 어느 버전 · 팔이 답했는지 — 배포 감시가 이 표시로 두 팔을 비교한다
        p.signals |= {"version": search_cfg["_version"], "arm": search_cfg.get("_arm")}
    with p.tracer.step("guard_context") as st:
        flagged = injection.scan_results(p.results)
        st["flagged"] = len(flagged)
        if flagged:
            p.guard["context"] = flagged
            if p.mode == "enforce":  # 지시가 숨은 문장은 LLM 에 넣지 않는다(간접 인젝션) — 같은 청크의 정상 내용은 남긴다
                bad = {f["chunk_id"] for f in flagged}
                kept = []
                for r in p.results:
                    if r.get("chunk_id") in bad:
                        clean, removed = injection.sanitize(r.get("text", ""))
                        st["removed_sentences"] = st.get("removed_sentences", 0) + len(removed)
                        if not clean.strip():  # 지시만 있던 청크는 통째로 뺀다
                            continue
                        r = r | {"text": clean}
                    kept.append(r)
                p.results = kept
    results = answer.compress(p.results, question, compress_keep) if compress_keep else p.results
    p.context, p.sources = answer.build_context(results, max_context_chars)
    note = ""
    if images and p.sources:
        p.images, note = answer.attach_images(db, p.sources, max_images)
    if p.mode == "off":
        system, ctx = answer.SYSTEM, p.context
    else:  # 근거를 데이터로 감싸 그 안의 지시를 따르지 않게(감지를 피한 간접 인젝션까지)
        system, ctx = injection.isolate(answer.SYSTEM, p.context)
    # 답 형식 지시(AS 의 '번호 단계로')는 질문이 아니라 시스템에 — 질문에 붙이면 검색 · 관련성 검증이 지시문까지 질문으로 읽는다
    p.system, p.prompt = system + (f"\n{instruction}" if instruction else ""), answer.user_prompt(question, ctx, note)
    return p


def finish(
    db: Session,
    p: Prepared,
    text: str,
    lcfg: llm.LLMConfig | None,
    *,
    usage: dict[str, Any] | None = None,
    llm_seconds: float = 0.0,
    kind: str = "answer",
    route: str = "",
    session_id: str | None = None,
    experiment_id: int | None = None,
    arm: str = "",
    client: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """LLM 답 뒤: 검증 → 출력 정책 · 개인정보 → 요청 기록. → 내보낼 답과 검사 결과."""
    usage = usage or {}
    if p.blocked:
        check: dict[str, Any] = {"sentences": [], "refused": True}
        final = p.blocked
        status = "blocked" if p.block_reason == "injection" else "ok"
        if status == "blocked":
            p.guard["action"] = "block"
    else:
        p.tracer.add("llm", llm_seconds * 1000, tokens_in=usage.get("input_tokens", 0), tokens_out=usage.get("output_tokens", 0))
        with p.tracer.step("verify"):
            check = answer.verify(text, p.sources, question=p.question if p.relevance else None)
            check["citations"] = legal.check_citations(text, p.sources, legal.lookup_fn_for(db, legal.chunk_set_of(db, p.search_cfg)))
        with p.tracer.step("guard_output"):
            pol = policy.check(text, p.domain, check)
        p.guard["output"] = {k: pol[k] for k in ("domain", "violations", "pii", "action")}
        if p.mode == "enforce":
            final = pol["fixed"]
        elif p.mode == "mask":
            final = pii.mask(text)[0]
        else:
            final = text
        p.guard["changed"] = final != text
        status = "blocked" if p.mode == "enforce" and pol["action"] == "block" else "ok"
    summary = {
        k: check.get(k) for k in ("supported_ratio", "relevant_ratio", "refused", "invalid_citations", "off_topic", "method") if k in check
    }
    if (c := check.get("citations")) and c.get("n"):
        summary["citations"] = {"n": c.get("n"), "not_found": sum(1 for r in c.get("refs", []) if r.get("status") == "not_found")}
    # AI 응답 고지(규제 대응 RC6, 인공지능 기본법 제31조 사전 고지 · 생성물 표시): 답 글에 섞지 않고 따로 돌려줘 화면이 늘 같은 자리에
    # 보이게 하고, 고지했는지를 요청 기록에 남긴다 — 정기 감사(RC8)가 '실제로 고지했나'를 이 기록으로 확인한다.
    notice = get_settings().ai_notice
    p.guard["notice"] = bool(notice)
    model = lcfg.model if lcfg else ""
    tin, tout = int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    t = tracing.record(
        db, kind=kind, user=p.user.name, groups=list(p.user.groups), client=client, session_id=session_id, collection_id=p.collection_id,
        question=p.question, answer=final, route=route, model=model, steps=p.tracer.steps, total_ms=p.tracer.total_ms,
        tokens_in=tin, tokens_out=tout, cost=tracing.cost_of(model, tin, tout),
        sources=[{"document_id": s.get("document_id"), "chunk_id": s.get("chunk_id"), "filename": s.get("filename")} for s in p.sources],
        verify=summary | (extra or {}), signals=p.signals, guard=p.guard, experiment_id=experiment_id, arm=arm, status=status,
    )  # fmt: skip
    return {"answer": final, "raw_answer": text, "verify": check, "guard": p.guard, "trace_id": t.id, "status": status,
            "signals": p.signals, "steps": p.tracer.steps, "total_ms": p.tracer.total_ms, "usage": usage, "notice": notice}  # fmt: skip


def answer_once(
    db: Session,
    question: str,
    search_cfg: dict[str, Any],
    lcfg: llm.LLMConfig,
    *,
    user: User = LOCAL,
    mode: str | None = None,
    max_tokens: int = 700,
    temperature: float = 0.1,
    **kw: Any,
) -> dict[str, Any]:
    """스트리밍이 필요 없는 곳(AS 상담 · 레드팀 · A/B)의 한 번에 답하기."""
    prep_keys = {"compress_keep", "max_context_chars", "images", "max_images", "instruction", "relevance"}
    p = prepare(db, question, search_cfg, user=user, mode=mode, **{k: v for k, v in kw.items() if k in prep_keys})
    fin_kw = {k: v for k, v in kw.items() if k not in prep_keys}
    if p.blocked or not p.sources:
        if not p.blocked:  # 검색 결과가 없으면 LLM 을 부르지 않는다
            p.blocked, p.block_reason = f"{answer.NOT_FOUND}.", "no_sources"
        out = finish(db, p, "", lcfg, **fin_kw)
    else:
        r = llm.chat(lcfg, p.system, p.prompt, max_tokens, temperature, images=p.images or None)
        out = finish(db, p, r["text"], lcfg, usage=r.get("usage"), llm_seconds=r.get("seconds", 0.0), **fin_kw)
    return out | {"sources": p.public_sources(), "search": p.search_meta}
