"""IO1 · IO2 도구 정의 · 권한: MCP 서버로 내보내는 도구 목록(이름 · 설명 · 입력 형식 · 범위)과 역할별 허용 범위.

도구를 적게, 설명은 '언제 쓰는가'까지 — 작은 모델은 도구가 많을수록 잘못 고른다(에이전트 실측: 번호 조회를 규칙으로 먼저 하게 하자
정답 근거 인용 75% → 100%). 범위(scope)는 읽기 · 쓰기 · 실행으로 나눠, 프롬프트 인젝션이 성공해도 할 수 있는 일을 줄인다:
읽기만 있으면 정보가 샐 수 있지만, 쓰기 · 실행이 있으면 시스템이 바뀐다.

검색처럼 연결 계층(pipeline)이 필요한 도구는 처리 함수를 API 가 등록한다(단계 로직은 pipeline 을 모른다 — 의존 방향 규칙).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import graphstore
from app.core.auth import User
from app.core.db import Chunk, ChunkSet, Collection
from app.stages.agent.agent import calc
from app.stages.rag import legal

SCOPES = ("read", "write", "exec")
# 역할별 허용 범위 — 실행(코드)은 관리자만. 쓰기는 '사람 검토 요청'처럼 되돌릴 수 있는 기록만 둔다
POLICY: dict[str, tuple[str, ...]] = {"admin": ("read", "write", "exec"), "user": ("read", "write")}


@dataclass
class Ctx:
    db: Session
    user: User
    trace_key: str = ""
    session: str = ""


Handler = Callable[[dict[str, Any], Ctx], dict[str, Any]]


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    scope: str = "read"
    handler: Handler | None = None
    untrusted: bool = False  # 결과가 신뢰 경계 밖에서 오는가(샌드박스 출력 · 외부 서버)
    annotations: dict[str, Any] = field(default_factory=dict)

    def spec(self) -> dict[str, Any]:
        """MCP tools/list 의 한 항목. annotations 는 MCP 의 도구 힌트(읽기 전용 · 파괴적 여부)."""
        hints = {"readOnlyHint": self.scope == "read", "destructiveHint": False, "openWorldHint": self.scope == "exec"}
        return {"name": self.name, "description": self.description, "inputSchema": self.schema, "annotations": hints | self.annotations}


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _list_collections(args: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    rows = ctx.db.scalars(select(Collection).order_by(Collection.id)).all()
    return {"collections": [{"id": c.id, "name": c.name, "domain": c.domain} for c in rows]}


def _read_chunk(args: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    c = ctx.db.get(Chunk, int(args["chunk_id"]))
    if c is None:
        raise ValueError("청크를 찾을 수 없습니다")
    return {"chunk_id": c.id, "document_id": c.document_id, "text": c.text}


def _lookup(args: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    cs = ctx.db.scalar(select(ChunkSet.id).where(ChunkSet.collection_id == int(args["collection_id"]), ChunkSet.status == "ready")
                       .order_by(ChunkSet.id.desc()))  # fmt: skip
    if cs is None:
        raise ValueError("컬렉션에 준비된 청크 세트가 없습니다")
    rows = legal.lookup(ctx.db, cs, str(args["ref"]))
    return {"results": [{k: r.get(k) for k in ("chunk_id", "document_id", "filename", "heading", "text")} for r in rows]}


def _calc(args: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    return {"result": calc(str(args["expression"]))}


def _graph(args: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    return graphstore.cypher_read(str(args["query"]), limit=100)


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("list_collections", "문서 컬렉션 목록(id · 이름 · 분야). 다른 도구에 넘길 collection_id 를 찾을 때 먼저 쓴다.", _obj({}, []),
             handler=_list_collections),
        Tool("search_documents", "컬렉션에서 질문과 관련된 문서 조각을 찾는다(BM25 + 의미 검색, 문서 권한 적용). 사실 · 규정 · 매뉴얼을 찾을 때.",
             _obj({"collection_id": {"type": "integer"}, "query": {"type": "string", "minLength": 1}, "top_k": {"type": "integer", "minimum": 1, "maximum": 20}},
                  ["collection_id", "query"])),
        Tool("lookup_article", "'근로기준법 제23조' · '2019다12345' 처럼 조문 · 사건번호가 질문에 있으면 검색보다 먼저 쓴다(번호로 바로 찾음).",
             _obj({"collection_id": {"type": "integer"}, "ref": {"type": "string", "minLength": 2}}, ["collection_id", "ref"]), handler=_lookup),
        Tool("read_chunk", "검색 결과의 chunk_id 로 그 조각 전문을 읽는다.", _obj({"chunk_id": {"type": "integer"}}, ["chunk_id"]), handler=_read_chunk),
        Tool("calculate", "산술식 계산(+ - * / ** % // 괄호). 금액 · 일수 계산을 LLM 이 암산하지 않게.",
             _obj({"expression": {"type": "string", "maxLength": 200}}, ["expression"]), handler=_calc),
        Tool("graph_query", "지식 그래프에 읽기 전용 Cypher 를 실행한다(쓰기 쿼리는 거절). 판례 → 조문 인용 · 집계 질문에.",
             _obj({"query": {"type": "string", "maxLength": 2000}}, ["query"]), handler=_graph),
        Tool("run_python", "파이썬 코드를 격리된 곳(네트워크 없음 · 시간 · 메모리 제한)에서 실행하고 표준 출력을 돌려준다. 표 · 수치 검증에. 관리자만.",
             _obj({"code": {"type": "string", "maxLength": 8000}}, ["code"]), scope="exec", untrusted=True),
        Tool("request_human_review", "AI 답(요청 기록 번호)을 사람이 다시 판단하도록 요청한다. 이용자가 사람 검토를 원할 때.",
             _obj({"trace_id": {"type": "integer"}, "reason": {"type": "string", "enum": ["wrong", "source", "human", "other"]},
                   "note": {"type": "string", "maxLength": 500}}, ["trace_id"]), scope="write"),
    ]
}  # fmt: skip


def register(name: str, handler: Handler) -> None:
    TOOLS[name].handler = handler


def allowed(user: User, tool: Tool) -> bool:
    return tool.scope in POLICY.get(user.role, ("read",))


def visible(user: User) -> list[Tool]:
    """tools/list 에는 쓸 수 있는 도구만 — 쓸 수 없는 도구를 보여 주면 LLM 이 고르고 거절당하는 헛걸음이 생긴다."""
    return [t for t in TOOLS.values() if allowed(user, t) and t.handler is not None]


def validate(tool: Tool, args: dict[str, Any]) -> str | None:
    """입력 형식 검사(필수 · 타입 · 범위 · 추가 키) — JSON Schema 라이브러리 없이, 이 도구들이 쓰는 만큼만."""
    props, req = tool.schema["properties"], tool.schema["required"]
    if missing := [k for k in req if k not in args]:
        return f"필수 입력이 없습니다: {', '.join(missing)}"
    if extra := [k for k in args if k not in props]:
        return f"모르는 입력: {', '.join(extra)}"
    types = {"integer": int, "string": str}
    for k, v in args.items():
        p = props[k]
        if not isinstance(v, types[p["type"]]) or (p["type"] == "integer" and isinstance(v, bool)):
            return f"{k} 는 {p['type']} 이어야 합니다"
        if "enum" in p and v not in p["enum"]:
            return f"{k} 는 {p['enum']} 중 하나"
        if isinstance(v, str) and (len(v) < p.get("minLength", 0) or len(v) > p.get("maxLength", 10**6)):
            return f"{k} 길이가 범위를 벗어났습니다"
        if isinstance(v, int) and not (p.get("minimum", -(10**9)) <= v <= p.get("maximum", 10**9)):
            return f"{k} 값이 범위를 벗어났습니다"
    return None
