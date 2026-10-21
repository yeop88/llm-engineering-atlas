"""S1 · S2 · S3 · S6 자원 현황: 캐시가 얼마나 맞나, 올라간 모델 · 장치, 근거 길이 설정 — 흩어진 설정 · 기록을 한 곳에.

새로 측정하지 않는다: 캐시 적중은 AS 의미 캐시 표(answer_cache.hits)와 검색 향상 변형 캐시, 모델은 모델 관리자(LRU), 장치는 런타임.
'무엇이 지금 메모리를 쓰고 있나'를 모르면 모델을 더 올리거나 캐시를 늘리는 결정을 할 수 없다.
"""

from typing import Any

import psutil
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import runtime
from app.core.config import get_settings
from app.core.db import AnswerCache
from app.stages.embedding.model_manager import get_manager
from app.stages.search_lab import enhance


def overview(db: Session) -> dict[str, Any]:
    st = get_settings()
    n_cache = db.scalar(select(func.count()).select_from(AnswerCache)) or 0
    hits = db.scalar(select(func.coalesce(func.sum(AnswerCache.hits), 0))) or 0
    loaded = [{"hf_id": lm.spec.hf_id, "profile": lm.profile, "device": lm.device, "dtype": lm.dtype, "load_seconds": round(lm.load_seconds, 1)}
              for lm in get_manager().loaded()]  # fmt: skip
    vm = psutil.virtual_memory()
    try:
        dev = runtime.accelerator() | {"resolved": runtime.resolve_device()}
    except Exception as exc:  # noqa: BLE001 — 장치 정보가 실패해도 나머지 현황은 보인다
        dev = {"error": str(exc)[:200]}
    return {
        "cache": {
            "answer_cache": {"entries": n_cache, "hits": int(hits)},
            "enhance_cache": {"entries": len(enhance.cache.data), "size": enhance.cache.size},
        },
        "models": {"loaded": loaded, "max_loaded": st.max_loaded_models},
        "device": dev | {"setting": st.device, "dtype": st.dtype},
        "memory": {
            "total_gb": round(vm.total / 2**30, 1),
            "used_pct": vm.percent,
            "process_mb": round(psutil.Process().memory_info().rss / 2**20),
        },
        "llm": {
            "model": st.openai_model,
            "urls": st.openai_model_urls,
            "small": st.small_llm_model,
            "fallbacks": len(st.llm_fallbacks or []),
        },
    }
