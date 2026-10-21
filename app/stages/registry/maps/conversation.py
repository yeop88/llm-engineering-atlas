"""대화 · 메모리 맵 — 맵 정의와 단계. 화면 · 메뉴 · 문서가 모두 여기서 나온다(scripts/gen_docs.py)."""

from app.stages.registry.model import DONE, Map, Page, Stage

MAP = Map("conversation", "대화 · 메모리 맵", "/maps/conversation", "docs/maps/conversation.md",
        summary="대화 맥락 질의 재작성 → 되묻기 → 대화 요약 메모리 → 사용자 · 제품 프로필 → 긴 대화 압축 → 상담원 이관 — 한 번이 아니라 이어지는 상담을 다루는 흐름",
        diagram="[대화 맥락 질의 재작성] → [되묻기 (모호한 질문)] → [대화 요약 메모리]\n"
                "                                      ↓\n"
                "[사용자 · 제품 프로필] → [긴 대화 압축]\n"
                "                                      ↓\n"
                "                         [상담원 이관 · 인계 요약]",
        lead="지금 답변은 질문 하나 단위입니다. 실제 고객 상담은 '그거 말고 다른 모델은요?' 처럼 앞 대화를 가리키고, 모호하면 되물어야 하고, 길어지면 앞부분을 잊지 않게 요약해야 하며, 안 되면 사람에게 넘겨야 합니다.",
        groups=(("질문 이해", ("cv_rewrite", "cv_clarify")),
                ("기억", ("cv_memory", "cv_profile", "cv_compress")),
                ("넘기기", ("cv_handoff",))),
        principles=("대화 맥락은 검색 전에 질문으로 풀어 쓴다 — 검색은 앞 대화를 모른다(검색 향상의 질의 재작성을 확장)",
                    "모르면 되묻는다 — 근거 밖에서 지어내는 것보다 낫다(답 없는 질문 거절이 약했던 법률 실측)",
                    "요약 · 압축은 품질을 잰다 — 근거 압축은 정답 문장을 버려 품질 −10 이었다",
                    "개인정보는 메모리에 오래 두지 않는다(보안 · 가드레일 맵)"),
        example="'세탁기 배수가 안 돼요' → '어느 모델인가요?'(되묻기) → '드럼 21kg 이요' → 프로필에 모델 저장 → '필터는 어디 있어요?' 를 '드럼 21kg 세탁기 배수 필터 위치' 로 바꿔 검색 → 해결 안 되면 대화 요약과 함께 상담원에게.")  # fmt: skip

STAGES: list[Stage] = [
    Stage(
        key="cv_rewrite",
        pages=[
            Page(
                "conversation_chat",
                "/conversation/chat",
                "대화 상담",
                "여러 턴 대화: 질문 풀어 쓰기 · 되묻기 · 기억 · 인계 요약",
                "conversation/chat.html",
            )
        ],
        no="C1",
        title="대화 맥락 질의 재작성",
        short="맥락 재작성",
        en="Contextual query rewriting",
        status=DONE,
        flow="conversation",
        map="conversation",
        builds_on=["search_lab"],
        summary="'그거 말고 다른 모델은요?' 처럼 앞 대화를 가리키는 질문을 혼자 읽혀도 되는 질문으로 바꿔 검색한다",
        principle="검색은 앞 대화를 모르므로, 대화 기록을 보고 대명사 · 생략을 채워 독립된 질문으로 다시 씁니다(대화형 질의 재작성). 재작성한 질문으로 검색하고 원래 질문으로 답합니다.",
        why="상담에서 두 번째 질문부터는 대부분 앞 대화에 기대 있습니다. 그대로 검색하면 엉뚱한 근거가 나옵니다.",
        how=[
            "앞 대화에 기대는 질문 판단(가리키는 말 · 말을 줄인 끝맺음 · 대상이나 기억한 제품이 빠진 짧은 질문) — 독립 질문은 바꾸지 않음",
            "풀어 쓰기 방법: 규칙(기억한 제품 · 대화 주제를 덧붙임, 지어내지 않음) · LLM(대화 기록 + 기억한 사실, 결과가 비거나 길면 규칙으로) · 앞 질문 이어 붙이기",
            "대화 상담 화면 · AS 상담 창(두 번째 문의부터)에 연결, 대화 평가 세트(후속 질문 24개)로 방법별 검색 비교",
        ],
        plans=["대화 평가 세트를 실제 상담 기록으로 늘리기"],
        docs=[
            ("대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측", "docs/stages/conversation/c1-rewrite/conversation.md"),
            ("대화 · 메모리 맵", "docs/maps/conversation.md"),
        ],
    ),
    Stage(
        key="cv_clarify",
        pages=[
            Page(
                "conversation_eval",
                "/conversation/eval",
                "대화 실측",
                "후속 질문 검색(풀어 쓰기 방법별) · 되묻기 · 메모리 정확도",
                "conversation/eval.html",
            )
        ],
        no="C2",
        title="되묻기 (모호한 질문)",
        short="되묻기",
        en="Clarifying questions",
        status=DONE,
        flow="conversation",
        map="conversation",
        builds_on=["routing"],
        summary="질문이 모호하거나 정보가 모자라면 답하기 전에 필요한 것을 되묻는다",
        principle="되묻기는 '어느 모델인가요?', '언제 계약하셨나요?' 처럼 답에 필요한 조건이 빠졌을 때 짧게 묻는 것입니다. 모호함은 검색 확신도 · 조건 누락 · 분류기로 판단합니다.",
        why="모호한 질문에 그럴듯하게 답하면 지어낸 답이 됩니다. 법률 실측에서 답 없는 질문을 거의 거절하지 못한 것과 같은 문제입니다.",
        how=[
            "필수 정보 빠짐: 제품별 매뉴얼 컬렉션에서 제품을 모르는 고장 문의 → '어느 모델인가요?'(코드가 한 모델에만 있으면 그 모델로 보고 묻지 않음)",
            "검색이 헷갈림: 짧은 질문(명사 2개 이하)인데 검색 1 · 2위 차가 아주 작음 → 구체적으로 물음",
            "한 대화에서 같은 이유로 두 번 묻지 않음(답하지 않으면 그대로 답함)",
        ],
        plans=["LLM 판단을 섞은 되묻기"],
        docs=[
            ("대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측", "docs/stages/conversation/c1-rewrite/conversation.md"),
            ("대화 · 메모리 맵", "docs/maps/conversation.md"),
        ],
    ),
    Stage(
        key="cv_memory",
        pages=[Page("conversation_memory", "/conversation/chat#memory", "기억한 사실", "제품 · 오류 코드 · 증상 · 안내한 조치 · 주제")],
        no="C3",
        title="대화 요약 메모리",
        short="대화 메모리",
        en="Conversation memory",
        status=DONE,
        flow="conversation",
        map="conversation",
        builds_on=["rag"],
        summary="대화가 길어져도 중요한 사실(제품 · 증상 · 이미 해 본 조치)을 요약해 기억한다",
        principle="대화 메모리는 지난 대화를 통째로 넣는 대신 사실 목록 · 요약으로 줄여 다음 답변에 넣는 것입니다. 무엇을 기억할지(결정 · 조건 · 해 본 조치)를 정해 둡니다.",
        why="대화를 통째로 넣으면 읽을 글이 계속 늘어 느려지고(근거 읽기가 이미 병목), 오래된 내용이 새 질문을 흐립니다.",
        how=[
            "규칙으로 사실 목록: 제품(컬렉션 문서 메타의 모델, 마지막에 말한 것) · 오류 코드(문서 제목 줄의 코드만) · 증상(개인정보 가림) · 답에서 안내한 번호 단계 · 대화 주제(첫 질문의 명사구)",
            "저장하지 않고 대화 기록에서 매번 다시 계산 — 기록과 어긋나지 않음, LLM 요약이 사실을 바꾸는 위험 없음",
        ],
        plans=["대화 중 주제 바뀜 감지"],
        docs=[
            ("대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측", "docs/stages/conversation/c1-rewrite/conversation.md"),
            ("대화 · 메모리 맵", "docs/maps/conversation.md"),
        ],
    ),
    Stage(
        key="cv_profile",
        pages=[Page("conversation_profile", "/conversation/chat#profile", "고객 프로필", "보유 제품 · 지난 문의")],
        no="C4",
        title="사용자 · 제품 프로필",
        short="프로필",
        en="User & product profile",
        status=DONE,
        flow="conversation",
        map="conversation",
        builds_on=["apps"],
        summary="고객의 보유 제품 · 이전 문의 · 선호를 프로필로 두고 검색 · 답변에 쓴다",
        principle="프로필은 대화를 넘어 남는 정보(보유 모델 · 구매일 · 이전 문의)입니다. 검색 필터(그 모델의 매뉴얼만)와 답변 맞춤에 씁니다.",
        why="같은 '배수가 안 돼요'도 모델마다 조치가 다릅니다. 매번 모델을 묻는 대신 프로필에서 가져오면 빠르고 정확합니다.",
        how=[
            "고객 키별 보유 제품 · 지난 문의 요약(가린 글), 보유 제품이 하나면 다음 대화의 시작 기억으로",
            "보관 기간(PROFILE_RETENTION_DAYS, 기본 90일)이 지나면 하루 한 번 지움, 화면에서 지우기",
        ],
        plans=["프로필로 검색 범위 · 추천 연결"],
        docs=[
            ("대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측", "docs/stages/conversation/c1-rewrite/conversation.md"),
            ("대화 · 메모리 맵", "docs/maps/conversation.md"),
        ],
    ),
    Stage(
        key="cv_compress",
        pages=[Page("conversation_compress", "/conversation/eval#retrieval", "긴 대화 압축", "최근 턴은 원문, 앞부분은 기억한 사실")],
        no="C5",
        title="긴 대화 압축",
        short="대화 압축",
        en="Long conversation compression",
        status=DONE,
        flow="conversation",
        map="conversation",
        builds_on=["rag"],
        summary="긴 대화 · 긴 근거를 품질을 지키며 줄여 문맥 한도 안에 넣는다",
        principle="긴 대화는 오래된 부분을 요약하고, 지금 질문과 관련된 부분만 남겨 문맥 한도 안에 넣습니다. 근거 압축과 같은 원리라 같은 위험(필요한 문장을 버림)이 있습니다.",
        why="로컬 LLM 의 문맥(슬롯당 8K)과 읽기 시간 때문에 긴 상담은 압축이 필요합니다. 근거 압축 실측(품질 −10)처럼 무엇을 버렸는지 재야 합니다.",
        how=[
            "답변 프롬프트에 최근 몇 턴(기본 4)만 원문, 그 앞은 기억한 사실 목록으로(규칙으로 뽑은 사실이라 요약이 사실을 바꾸지 않음), 1,500자 한도",
        ],
        plans=["압축 전후 답변 품질 비교"],
        docs=[
            ("대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측", "docs/stages/conversation/c1-rewrite/conversation.md"),
            ("대화 · 메모리 맵", "docs/maps/conversation.md"),
        ],
    ),
    Stage(
        key="cv_handoff",
        pages=[Page("conversation_handoff", "/conversation/chat#handoff", "상담원 인계", "인계 요약")],
        no="C6",
        title="상담원 이관 · 인계 요약",
        short="상담원 이관",
        en="Human handoff",
        status=DONE,
        flow="conversation",
        map="conversation",
        builds_on=["apps", "routing"],
        summary="자동으로 풀 수 없거나 위험한 문의는 대화 요약과 함께 사람에게 넘긴다",
        principle="이관 기준(반복 실패 · 불만 · 안전 관련 · 고객 요청)을 정하고, 넘길 때는 대화 요약 · 시도한 조치 · 근거를 붙여 상담원이 처음부터 묻지 않게 합니다.",
        why="자동 답변이 모든 것을 해결할 수는 없습니다. 이관이 늦거나 맥락 없이 넘어가면 고객 경험이 가장 나빠집니다.",
        how=[
            "인계 요약: 제품 · 코드 · 증상 · 이미 안내한 조치 · 처음과 마지막 질문 · 고객 말 수 — AS 상담은 이 요약을 담은 티켓으로 이관(AS7)",
        ],
        plans=["이관 후 해결 시간 지표"],
        docs=[
            ("대화 · 메모리 — 재작성 · 되묻기 · 메모리 · 실측", "docs/stages/conversation/c1-rewrite/conversation.md"),
            ("대화 · 메모리 맵", "docs/maps/conversation.md"),
        ],
    ),
]
