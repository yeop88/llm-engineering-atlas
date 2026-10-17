"""검색 연결점: 2 RAG 검색(+3 리랭킹)에 4 검색 향상을 끼워 넣는다.

모든 검색 호출(검색 비교 · 조합 평가 · 답변 생성 · 답변 평가)이 이 함수를 거치게 해서, 설정에
enhance 만 넣으면 어느 화면에서든 같은 방식으로 검색 향상이 적용되게 한다. 나중에 라우팅 등
다음 단계도 여기에 이어 붙인다.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.stages.rag import service
from app.stages.search_lab import enhance

# API 가 평가 라벨 등에 기법 이름을 쓸 때 stages.search_lab 을 직접 가져가지 않도록 여기서 내보낸다(의존 방향 유지).
ENHANCE_LABEL = enhance.TECHNIQUES


def run_search(db: Session, query: str, cfg: dict[str, Any]) -> dict[str, Any]:
    tech = (cfg.get("enhance") or {}).get("technique") or "none"
    if tech == "none":
        # 기법을 끄면 이전과 완전히 같은 경로(service.search)로 간다 — 기준선 결과가 바뀌지 않게.
        return service.search(db, query, cfg)
    return enhance.search(db, query, cfg)
