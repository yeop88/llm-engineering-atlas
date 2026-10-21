"""MA6 보고서 작성 에이전트: 모은 근거 · 분석 결과로 답을 쓴다 — 쉬운 작성은 소형 모델, 어려운 작성은 큰 모델.

난이도는 라우팅(6)의 규칙 라우터로 나눈다(이유 · 방법 · 비교를 묻거나 길거나 여러 가지를 함께 물으면 어려움). 소형 모델(SMALL_LLM_*)이
없으면 모두 기본 모델 — 라우팅 실측에서 쉬운 질문을 소형 경로로 보내 지연을 줄였던 것과 같은 생각이다.
분석 결과가 있으면 그 숫자를 그대로 쓰게 하고(새로 계산하지 말 것), 검증 에이전트의 수정 요청이 오면 그 지적을 반영해 다시 쓴다.
"""

from typing import Any

from app.core import llm
from app.core.config import get_settings
from app.stages.rag import answer
from app.stages.routing import routers


def models(default: llm.LLMConfig) -> dict[str, llm.LLMConfig]:
    st = get_settings()
    small = default
    if st.small_llm_model:
        small = llm.LLMConfig(
            "openai", st.small_llm_model, (st.small_llm_base_url or st.openai_base_url).rstrip("/"), st.openai_api_key, st.llm_timeout
        )
    return {"easy": small, "hard": default}


def write(question: str, sources: list[dict[str, Any]], analysis: dict[str, Any] | None, lcfg: llm.LLMConfig,
          feedback: str = "", previous: str = "") -> dict[str, Any]:  # fmt: skip
    level, why = routers.route_rule(question)
    cfg = models(lcfg)[level]
    ctx, used = answer.build_context(sources)  # 번호가 붙은 근거만 used — 검증이 같은 번호로 대 보게 함께 돌려준다
    extra = ""
    if analysis and analysis.get("ok"):
        extra = f"\n\n[분석 결과 — 이 숫자를 그대로 쓰고 새로 계산하지 마세요]\n{analysis['result']}"
    if feedback:
        extra += f"\n\n[검증 에이전트의 지적 — 반영해 다시 쓰세요]\n{feedback}\n\n[앞선 답]\n{previous}"
    r = llm.chat(cfg, answer.SYSTEM, f"[근거]\n{ctx}{extra}\n\n[질문]\n{question}", max_tokens=700, temperature=0.1)
    return {
        "text": r["text"],
        "level": level,
        "why": why,
        "model": cfg.model,
        "usage": r.get("usage"),
        "seconds": r.get("seconds"),
        "used": used,
    }
