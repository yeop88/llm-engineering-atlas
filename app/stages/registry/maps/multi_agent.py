"""멀티에이전트 · 멀티모달 맵 — 맵 정의와 단계. 화면 · 메뉴 · 문서가 모두 여기서 나온다(scripts/gen_docs.py).

멀티모달 = 처리하는 데이터의 종류를 넓힘(앞단 입력 · 검색, 뒷단 출력), 멀티에이전트 = 처리 과정을 전문가 협업으로 넓힘(라우터 자리를 오케스트레이터가).
이미 있는 것(멀티모달 임베딩 · 이미지 컬렉션 · 그림 근거 답변, 에이전트 도구, 라우팅 · 소형 모델, 답변 검증)을 상태에 그대로 반영한다.
"""

from app.stages.registry.model import DONE, Map, Page, Stage

MAP = Map("agents", "멀티에이전트 · 멀티모달 맵", "/maps/multi-agent", "docs/maps/multi-agent.md", template="maps/multi_agent.html", summary=
        "멀티모달 입력 · 검색 → 오케스트레이터가 전문가 에이전트(검색 · 분석 · 작성 · 검증)에게 분배 → 교차 검증 → 텍스트 · 차트 · 음성 출력",
        diagram="[멀티모달 입력 (텍스트 · 이미지 · 음성 · 문서)] → [멀티모달 임베딩]\n"
        "                                        ↓\n"
        "                     [오케스트레이터 에이전트 (작업 분해 · 분배)]\n"
        "          ↓                             ↓                              ↓\n"
        "  [검색 전문가 (멀티모달 RAG)]   [분석 · 코딩 (표 · 코드 · 차트)]   [보고서 작성 (sLLM / LLM)]\n"
        "                                        ↓\n"
        "                     [품질 검증 (Critic) · 교차 검증]\n"
        "                                        ↓\n"
        "                [멀티모달 출력 (텍스트 + 차트 + 음성)]")  # fmt: skip

STAGES: list[Stage] = [
    Stage(
        key="mm_input",
        pages=[
            Page(
                "ma_image",
                "/multiagent/image-search",
                "사진으로 찾기",
                "사진 + 질문으로 멀티모달 인덱스 검색",
                "multiagent/image_search.html",
            )
        ],
        no="MA1",
        title="멀티모달 입력 · 임베딩",
        short="멀티모달 임베딩",
        en="Multimodal input & embedding",
        status=DONE,
        flow="agents",
        map="agents",
        builds_on=["multimodal", "embedding"],
        summary="텍스트 · 이미지 · 음성 · 문서를 공통 벡터 공간에 놓아, 사진으로 매뉴얼을 찾는 식의 교차 검색을 한다",
        principle="멀티모달 임베딩 모델(CLIP · SigLIP · ImageBind · 멀티모달 EmbeddingGemma 등)은 이미지와 텍스트(모델에 따라 음성까지)를 같은 벡터 공간에 놓습니다. "
        "그래서 이미지 자체를 질의로 써서 비슷한 텍스트 · 이미지를 찾을 수 있습니다(예: 제품 사진 → 관련 매뉴얼).",
        why="고객 · AS 문의는 '이 에러 화면' · '이 부품' 처럼 사진으로 들어오는 경우가 많습니다. 사진을 글로 옮겨 적게 하면 정보가 빠지고 사용자가 불편합니다.",
        how=[
            "(있음) LLM 맵 M 멀티모달: 이미지 · 영상 장면을 텍스트와 같은 공간에서 검색",
            "사진을 올려 컬렉션 인덱스의 멀티모달 모델로 임베딩해 그림 · 글 청크를 찾고, 질문 글을 함께 주면 그림 · 글 임베딩 평균으로 '이 사진 + 이 질문'",
            "문서 권한(G3)은 그림 검색에도, 텍스트 전용 인덱스는 거절",
        ],
        plans=["음성 입력(STT) 연결 — 음성 상담 맵과 함께"],
        docs=[
            (
                "멀티에이전트 · 멀티모달 — 오케스트레이터 · 전문가 에이전트 · 멀티모달 입출력 · 실측",
                "docs/stages/multi-agent/ma3-orchestrator/multiagent.md",
            ),
            ("멀티에이전트 · 멀티모달 맵", "docs/maps/multi-agent.md"),
            ("LLM 맵 · 멀티모달", "docs/stages/llm/m-multimodal/multimodal.md"),
        ],
    ),
    Stage(
        key="mm_rag",
        pages=[Page("ma_rerank", "/multiagent/console#timeline", "멀티모달 RAG", "그림 후보를 비전 LLM 으로 다시 줄 세움")],
        no="MA2",
        title="멀티모달 RAG",
        en="Multimodal RAG",
        status=DONE,
        flow="agents",
        map="agents",
        builds_on=["rag", "multimodal", "rerank"],
        summary="표 · 그래프 · 설계도를 글로 바꾸지 않고 이미지 청크 그대로 저장 · 검색하고, 멀티모달로 다시 순위를 매긴다",
        principle="PDF 안의 복잡한 표 · 그래프 · 설계도는 글로 뽑으면 구조가 깨집니다. 페이지나 그림 영역을 이미지 청크로 그대로 저장해 멀티모달 임베딩으로 찾고, "
        "찾은 이미지는 비전 LLM 이 직접 읽어 답합니다.",
        why="사내 문서의 핵심 정보가 표 · 도면에 있는 경우가 많고, 텍스트 추출만으로는 '이 그래프의 추세'나 '도면의 부품 번호'를 답할 수 없습니다.",
        how=[
            "(있음) 이미지 · 영상 프레임을 청크로 색인 · 검색, 그림 근거를 비전 LLM 에 첨부해 번호로 인용",
            "검색 전문가가 그림 후보를 비전 LLM 에 질문과 함께 보여 0~3점을 받아 다시 줄 세움(글 임베딩이 놓친 그림 속 표 · 도면 보완), 실패하면 원래 순서",
        ],
        plans=["PDF 표 · 그림 영역을 이미지 청크로"],
        docs=[
            (
                "멀티에이전트 · 멀티모달 — 오케스트레이터 · 전문가 에이전트 · 멀티모달 입출력 · 실측",
                "docs/stages/multi-agent/ma3-orchestrator/multiagent.md",
            ),
            ("멀티에이전트 · 멀티모달 맵", "docs/maps/multi-agent.md"),
            ("LLM 연결 · 그림 근거 답변", "docs/guides/llm.md"),
        ],
    ),
    Stage(
        key="orchestrator",
        pages=[
            Page(
                "ma_console",
                "/multiagent/console",
                "에이전트 협업",
                "오케스트레이터 · 전문가 에이전트 흐름 · 멀티모달 출력",
                "multiagent/console.html",
            )
        ],
        no="MA3",
        title="오케스트레이터 에이전트",
        short="오케스트레이터",
        en="Orchestrator agent",
        status=DONE,
        flow="agents",
        map="agents",
        builds_on=["routing", "agent"],
        summary="복잡한 요청을 작업으로 쪼개(Task Decomposition) 전문가 에이전트에게 나눠 주고 결과를 모은다 — 라우터 자리의 진화",
        principle="오케스트레이터는 '작년 분기별 매출 그래프를 분석해 보고서를 쓰고 요약해 줘' 같은 요청을 검색 → 분석 → 작성 → 검증 작업으로 나누고, "
        "작업마다 맞는 전문가 에이전트를 부르며, 중간 결과를 다음 작업에 넘깁니다. LLM 맵의 라우터가 '어느 경로로 보낼까'만 정했다면, 오케스트레이터는 '어떤 순서로 누구에게 무엇을' 정합니다.",
        why="하나의 모델이 검색 · 계산 · 글쓰기 · 검증을 다 하면 프롬프트가 길고 실패 지점이 섞여 어디서 틀렸는지 알 수 없습니다. 역할을 나누면 에이전트마다 작은 모델 · 도구 · 검증을 따로 고를 수 있습니다. "
        "다만 이 PC 의 실측에서 작은 로컬 모델은 여러 단계를 거친 답에서 근거 밖 문장이 늘었습니다(에이전트 문장 근거율 50% vs RAG 91%) — 단계를 늘릴수록 단계마다 검증이 필요합니다.",
        how=[
            "요청 → 작업 계획(검색은 늘, 분석은 계산 · 비교 · 표를 물을 때, 작성 뒤엔 늘 검증) — 규칙으로, LLM 계획은 쓰지 않음(에이전트가 다섯뿐이고 '검증 빼기' 같은 실수를 막으려고)",
            "에이전트끼리 칠판(board)에 결과를 쌓고, 주고받음을 시간과 함께 남겨 화면에 그대로",
            "결과는 실행 기록과 요청 기록(감사 · 고지) 둘 다에",
        ],
        plans=["외부 에이전트(A2A)를 전문가로 부르기"],
        docs=[
            (
                "멀티에이전트 · 멀티모달 — 오케스트레이터 · 전문가 에이전트 · 멀티모달 입출력 · 실측",
                "docs/stages/multi-agent/ma3-orchestrator/multiagent.md",
            ),
            ("멀티에이전트 · 멀티모달 맵", "docs/maps/multi-agent.md"),
            ("LLM 맵 · 에이전트 실측", "docs/stages/llm/8a-agent/agent.md"),
        ],
    ),
    Stage(
        key="retrieval_agent",
        pages=[Page("ma_retrieval", "/multiagent/console#timeline", "검색 전문가", "검색 → 충분성 → 질의 고쳐 다시")],
        no="MA4",
        title="검색 전문가 에이전트",
        short="검색 에이전트",
        en="Retrieval agent (Self-RAG)",
        status=DONE,
        flow="agents",
        map="agents",
        builds_on=["agent", "search_lab", "rag"],
        summary="사내 문서 · 이미지 · 웹 검색만 맡고, 결과가 부실하면 스스로 질의를 고쳐 다시 찾는다(Self-RAG)",
        principle="검색 에이전트는 '정보 모으기'만 전담합니다. 찾은 결과가 질문에 충분한지 스스로 판단하고, 부족하면 질의를 바꾸거나 하위 질문으로 나눠 다시 검색합니다. "
        "모은 근거는 번호를 붙여 다음 에이전트에게 넘깁니다.",
        why="검색이 부실하면 뒤의 분석 · 작성이 아무리 좋아도 답이 틀립니다. 검색만 따로 두면 검색 품질을 기존 평가 세트(nDCG · 근거 검색률)로 따로 잴 수 있습니다.",
        how=[
            "검색 → 충분성 판단(질문 핵심 낱말이 근거에 나오는 비율, 애매할 때만 LLM 판정) → 부족하면 '부족한 것'을 덧붙여 질의 재작성(4 검색 향상) → 다시(상한 3번)",
            "회차마다 질의 · 찾은 수 · 덮음 · 판정 방식을 남김",
        ],
        plans=["웹 검색 도구"],
        docs=[
            (
                "멀티에이전트 · 멀티모달 — 오케스트레이터 · 전문가 에이전트 · 멀티모달 입출력 · 실측",
                "docs/stages/multi-agent/ma3-orchestrator/multiagent.md",
            ),
            ("멀티에이전트 · 멀티모달 맵", "docs/maps/multi-agent.md"),
        ],
    ),
    Stage(
        key="analysis_agent",
        pages=[Page("ma_analysis", "/multiagent/console#timeline", "분석 · 코딩", "근거 수치를 코드로 계산 · 차트")],
        no="MA5",
        title="분석 · 코딩 에이전트",
        short="분석 에이전트",
        en="Analysis / code agent",
        status=DONE,
        flow="agents",
        map="agents",
        builds_on=["agent", "io_sandbox"],
        summary="검색된 표 · 수치를 파이썬 코드로 계산 · 검증하고 결과 차트를 만든다",
        principle="LLM 이 계산을 머릿속으로 하면 틀립니다. 분석 에이전트는 표 · 그래프 데이터를 파싱해 코드를 만들고, 격리된 실행기(코드 인터프리터)에서 실행한 결과로 통계 · 무결성 검증 · 차트를 냅니다.",
        why="'분기별 매출 증감률', '보증금 반환 금액 계산' 같은 질문은 숫자를 정확히 계산해야 합니다. 실행 결과를 근거로 쓰면 계산 과정을 재현 · 검증할 수 있습니다.",
        how=[
            "LLM 은 근거 글(SOURCES)에서 수치를 뽑아 계산하는 파이썬 코드만 쓰고, 계산은 샌드박스(IO2, 네트워크 없는 컨테이너)가 — 작은 모델의 암산 오류를 피하려고",
            "결과는 JSON 한 줄(result · chart), 실패하면 오류를 보여 한 번 다시 쓰게",
        ],
        plans=[],
        docs=[
            (
                "멀티에이전트 · 멀티모달 — 오케스트레이터 · 전문가 에이전트 · 멀티모달 입출력 · 실측",
                "docs/stages/multi-agent/ma3-orchestrator/multiagent.md",
            ),
            ("멀티에이전트 · 멀티모달 맵", "docs/maps/multi-agent.md"),
        ],
    ),
    Stage(
        key="report_agent",
        pages=[Page("ma_writer", "/multiagent/console#output", "보고서 작성", "난이도별 모델 · 분석 숫자 그대로")],
        no="MA6",
        title="보고서 작성 에이전트",
        short="작성 에이전트",
        en="Writer agent (sLLM / LLM routing)",
        status=DONE,
        flow="agents",
        map="agents",
        builds_on=["routing", "rag"],
        summary="모은 근거 · 분석 결과로 정해진 형식의 답 · 보고서를 쓴다 — 쉬운 작성은 소형 모델, 어려운 작성은 큰 모델",
        principle="작성 에이전트는 근거와 분석 결과를 받아 템플릿(보고서 · 안내문 · 요약)에 맞춰 씁니다. 짧은 요약 · 정형 안내는 소형 모델(sLLM)로, 긴 종합 · 추론은 큰 모델로 보냅니다.",
        why="같은 품질이면 싼 모델을 써야 하지만, 작은 모델로 바꾸면 품질이 떨어질 수 있습니다. 이 PC 실측에서 Gemma 4 E2B 는 E4B 보다 지연 −21% 대신 품질 −13(유의)이라, 작성 난이도에 따라 나눠 써야 합니다.",
        how=[
            "라우팅(6) 규칙으로 쉬움 · 어려움 — 쉬우면 소형 모델(SMALL_LLM_MODEL · SMALL_LLM_BASE_URL), 어려우면 기본 모델",
            "분석 결과의 숫자는 그대로 쓰고 새로 계산하지 않게, 검증 에이전트의 지적이 오면 반영해 다시 씀",
        ],
        plans=[],
        docs=[
            (
                "멀티에이전트 · 멀티모달 — 오케스트레이터 · 전문가 에이전트 · 멀티모달 입출력 · 실측",
                "docs/stages/multi-agent/ma3-orchestrator/multiagent.md",
            ),
            ("멀티에이전트 · 멀티모달 맵", "docs/maps/multi-agent.md"),
            ("LLM 맵 · 소형 모델 실측", "docs/stages/llm/7b-quant/quant.md"),
        ],
    ),
    Stage(
        key="critic_agent",
        pages=[Page("ma_critic", "/multiagent/console#timeline", "품질 검증", "통과 · 수정 요청 · 반려 · 재작성 루프")],
        no="MA7",
        title="품질 검증 에이전트",
        short="검증 에이전트",
        en="Critic / reviewer agent",
        status=DONE,
        flow="agents",
        map="agents",
        builds_on=["rag", "rl"],
        summary="최종 답이 원문과 맞는지(환각) · 질문에 답하는지 · 보안 규정을 어기지 않는지 검사해 반려하거나 통과시킨다",
        principle="검증 에이전트는 답을 만들지 않고 검사만 합니다. 문장마다 근거 일치 · 질문 관련성 · 인용 번호를 확인하고, 규정(개인정보 · 내부 정보 노출 등)을 점검해 "
        "통과 / 수정 요청 / 반려를 정합니다. 반려되면 작성 에이전트가 이유를 받아 다시 씁니다(교차 검증).",
        why="에이전트가 많아질수록 앞 단계의 실수가 뒤로 전달됩니다. 마지막에 독립된 검사가 있어야 서비스로 내보낼 수 있습니다. "
        "다만 이 PC 의 사람 판정에서 작은 LLM 판정은 근거 일치를 28개 모두 통과시켰습니다 — 검증 에이전트는 LLM 판단만이 아니라 측정으로 보정된 점수를 함께 써야 합니다.",
        how=[
            "문장별 근거 일치 · 질문 관련성(2 RAG), 출력 정책 · 개인정보(G4 · G2), 분석 숫자가 답에 있나를 보고 통과 · 수정 요청(지적과 함께) · 반려(규정 위반)",
            "수정 요청이면 작성 에이전트가 다시(상한 2번), 상한에 닿으면 '검토 필요' 표시를 붙여 내보냄",
        ],
        plans=[],
        docs=[
            (
                "멀티에이전트 · 멀티모달 — 오케스트레이터 · 전문가 에이전트 · 멀티모달 입출력 · 실측",
                "docs/stages/multi-agent/ma3-orchestrator/multiagent.md",
            ),
            ("멀티에이전트 · 멀티모달 맵", "docs/maps/multi-agent.md"),
            ("LLM 맵 · 답변 원칙과 검증", "docs/stages/llm/2-rag/rag.md"),
        ],
    ),
    Stage(
        key="mm_output",
        pages=[Page("ma_output", "/multiagent/console#output", "멀티모달 출력", "글 · 차트 · 근거 그림 · 음성")],
        no="MA8",
        title="멀티모달 출력",
        en="Multimodal output",
        status=DONE,
        flow="agents",
        map="agents",
        builds_on=["multimodal"],
        summary="텍스트 답에 더해 차트 · 이미지 · 음성으로 결과를 낸다",
        principle="수집한 이미지 · 표 근거와 분석 결과를 함께 써서, 글 답변 외에 새 차트 · 요약 이미지 · 음성(TTS) 안내를 만듭니다. 출력도 근거 번호와 검증을 따릅니다.",
        why="'그래프로 보여 줘', '현장에서 들을 수 있게' 같은 요구는 글만으로 채울 수 없습니다. AS 수리 안내는 단계별 그림 · 음성이 더 쓸모 있습니다.",
        how=[
            "글 답 + 분석 결과 차트(데이터로 보내 화면이 Chart.js 로, 색은 --series 토큰 · 표로 보기) + 근거 그림 + 음성(TTS_URL, OpenAI 호환 /audio/speech — 근거 번호는 읽지 않게 뺌)"
        ],
        plans=[],
        docs=[
            (
                "멀티에이전트 · 멀티모달 — 오케스트레이터 · 전문가 에이전트 · 멀티모달 입출력 · 실측",
                "docs/stages/multi-agent/ma3-orchestrator/multiagent.md",
            ),
            ("멀티에이전트 · 멀티모달 맵", "docs/maps/multi-agent.md"),
        ],
    ),
]
