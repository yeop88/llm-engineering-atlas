"""추론 모델 · 테스트 시간 연산 맵 — 맵 정의와 단계. 화면 · 메뉴 · 문서가 모두 여기서 나온다(scripts/gen_docs.py)."""

from app.stages.registry.model import DONE, Map, Page, Stage

MAP = Map('reasoning', '추론 모델 · 테스트 시간 연산 맵', '/maps/reasoning', 'docs/maps/reasoning.md',
        summary='생각 예산 → 생각할지 말지 라우팅 → 여러 번 풀고 고르기 → 검증기 · 과정 보상 → 생각 과정 검사 → 추론 증류 — 생각하는 LLM 을 서비스에 쓰는 흐름',
        diagram='[생각 예산] → [생각할지 말지 라우팅]\n                    ↓\n[여러 번 풀고 고르기] → [검증기 · 과정 보상]\n                    ↓\n[생각 과정 검사] → [추론 증류]',
        lead="추론 모델은 답 전에 긴 '생각'을 써서 어려운 문제의 정확도를 올리지만 토큰 · 지연이 몇 배로 늡니다. 이 PC 처럼 생성이 초당 13 토큰이면 생각 2,000 토큰이 2분 반입니다. 언제 · 얼마나 생각하게 할지, 여러 답 중 무엇을 고를지를 실측으로 정하는 맵입니다. 생각 끄기 설정(LLM_DISABLE_THINKING) · Best-of-N · 검증 가능한 보상(RLVR)이 출발점입니다.",
        groups=(('얼마나 생각할까', ('rs_budget', 'rs_route')), ('여러 답 중 고르기', ('rs_sampling', 'rs_verifier')), ('믿을 수 있나 · 싸게', ('rs_trace', 'rs_distill'))),
        principles=('생각은 비용이다 — 정답률이 오르는 구간까지만(이 PC 생성 13 토큰/초)', '고르기는 검증기가 정확한 만큼만 낫다 — Best-of 실측의 보상-품질 짝 비교', '쉬운 질문은 생각하지 않는다 — 라우팅 실측처럼 질문 난이도로 나눈다', '생각 과정도 출력이다 — 근거 밖 사실 · 개인정보 검사 대상'),
        example="법률 질문 '임금 체불이 3개월이면 지연이자는?' → 라우터가 조문 결합 · 계산이 필요하다고 판단 → 생각 예산 1,024 토큰으로 5번 풀기 → 조문 번호 · 계산을 검증기로 확인해 다수결 → 생각 과정의 근거 밖 조문 인용 검사 → 같은 유형은 작은 모델에 증류한 풀이로.")  # fmt: skip

STAGES: list[Stage] = [
    Stage(
        key="rs_budget",
        pages=[
            Page(
                "rs_budget",
                "/reasoning/budget",
                "생각 예산 · 라우팅",
                "예산별 정답률 · 생각 토큰 · 꺾이는 점, 생각 라우터 채점",
                "reasoning/budget.html",
            )
        ],
        no="RS1",
        title="생각 예산",
        short="생각 예산",
        en="Thinking budget",
        status=DONE,
        flow="reasoning",
        map="reasoning",
        builds_on=["sv_budget"],
        summary="생각 토큰 상한을 바꿔 가며 정답률 · 지연 · 비용 곡선을 잰다",
        principle="생각 예산은 답 전에 쓸 수 있는 생각 토큰의 상한입니다. 상한을 늘리면 어려운 문제의 정답률이 오르다가 평평해지고, 지연 · 비용은 계속 늡니다.",
        why="어느 지점에서 정답률이 더 오르지 않는지 모르면 예산을 감으로 정하게 됩니다. 질문 유형마다 그 지점이 다릅니다.",
        how=[
            "(기반) 비용 · 지연 예산(S7) · 생각 끄기 설정, 검증 가능한 과제(RV1)",
            "RLVR 과제를 예산(0 = 생각 끔 · 256 · 512 · 1024 · 2048)별로 풀어 정답률 · 생각 토큰 · 시간 · 유형별 '꺾이는 점'(최고 정답률에서 허용 폭 안의 가장 작은 예산)",
            "예산 강제: 생각이 예산을 넘으면 잘린 생각을 붙여 생각 없이 답만 쓰게 — 생각 예산 인자가 없는 서버에서도 같은 상한, Claude API 는 확장 생각 예산",
        ],
        plans=[],
        docs=[
            (
                "추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측",
                "docs/stages/reasoning/rs1-budget/reasoning.md",
            ),
            ("추론 모델 · 테스트 시간 연산 맵", "docs/maps/reasoning.md"),
        ],
    ),
    Stage(
        key="rs_route",
        pages=[Page("rs_route", "/reasoning/budget#route", "생각 라우팅", "늘 끔 · 늘 켬 · 라우터 · 이상적")],
        no="RS2",
        title="생각할지 말지 라우팅",
        short="생각 라우팅",
        en="Adaptive reasoning",
        status=DONE,
        flow="reasoning",
        map="reasoning",
        builds_on=["routing"],
        summary="질문 난이도를 보고 생각 모드 · 예산을 고른다",
        principle="적응형 추론은 쉬운 질문은 바로 답하고, 계산 · 여러 조문 결합 · 다단계 질문만 생각하게 하는 것입니다. 라우터가 난이도를 미리 판단합니다.",
        why="모든 질문에 생각을 켜면 쉬운 질문까지 몇 배 느려집니다. 라우팅 실측처럼 질문을 나누면 같은 품질을 싸게 얻습니다.",
        how=[
            "(기반) 규칙 · 확신도 · 학습 라우터(6)",
            "질문 글만 보고 생각을 켤지: 규칙(계산 · 집계 · 결합 표현) 또는 LLM(생각 없이 한 낱말)",
            "같은 과제의 끔 · 켬 풀이로 네 정책(늘 끔 · 늘 켬 · 라우터 · 이상적)의 정답률 · 평균 토큰 · 시간 · 유형별 켠 비율",
        ],
        plans=[],
        docs=[
            (
                "추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측",
                "docs/stages/reasoning/rs1-budget/reasoning.md",
            ),
            ("추론 모델 · 테스트 시간 연산 맵", "docs/maps/reasoning.md"),
        ],
    ),
    Stage(
        key="rs_sampling",
        pages=[
            Page(
                "rs_sampling",
                "/reasoning/sampling",
                "여러 번 풀기 · 검증기",
                "표본 수별 다수결 · 검증기 고르기 · pass@n · 검증기 AUROC",
                "reasoning/sampling.html",
            )
        ],
        no="RS3",
        title="여러 번 풀고 고르기",
        short="여러 번 풀기",
        en="Self-consistency & Best-of-N",
        status=DONE,
        flow="reasoning",
        map="reasoning",
        builds_on=["rl"],
        summary="같은 질문을 여러 번 풀어 다수결 · 점수로 고른다",
        principle="자기 일관성은 같은 문제를 여러 번 풀어 가장 많이 나온 답을 고르고, Best-of-N 은 점수 함수로 가장 좋은 답을 고릅니다. 연산을 더 써서 정확도를 사는 방법입니다.",
        why="몇 번까지 풀어야 이득인지, 다수결과 점수 고르기 중 무엇이 나은지는 과제마다 다릅니다.",
        how=[
            "(기반) Best-of-N · 보상 함수(8b)",
            "온도를 두고 n 번 풀어 풀이 저장소에 쌓고, n = 1 … N 의 다수결(정규화한 답의 최빈값) · 검증기 고르기 · pass@n(상한) 곡선을 한 번에 — 앞 n 개만 써서 새로 부르지 않음",
        ],
        plans=[],
        docs=[
            (
                "추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측",
                "docs/stages/reasoning/rs1-budget/reasoning.md",
            ),
            ("추론 모델 · 테스트 시간 연산 맵", "docs/maps/reasoning.md"),
        ],
    ),
    Stage(
        key="rs_verifier",
        pages=[Page("rs_verifier", "/reasoning/sampling#verifier", "검증기 정확도", "형식 · 근거에 있음 · 과정 채점 · LLM 판정")],
        no="RS4",
        title="검증기 · 과정 보상",
        short="검증기",
        en="Verifiers & process rewards",
        status=DONE,
        flow="reasoning",
        map="reasoning",
        builds_on=["rv_reward", "critic_agent"],
        summary="답 · 풀이 단계를 검증기로 채점해 고른다",
        principle="검증기는 답이 맞는지 판정하는 모델 · 규칙이고, 과정 보상 모델은 풀이의 각 단계를 채점합니다. 고르기의 품질은 검증기의 정확도를 넘지 못합니다.",
        why="LLM 판정은 그 자체가 틀립니다(검증 보정 실측). 규칙으로 확인할 수 있는 것(조문 번호 · 숫자)은 규칙으로, 나머지는 판정의 정확도를 따로 잽니다.",
        how=[
            "(기반) 검증 가능한 보상(RV3) · 검증 에이전트(MA7)",
            "정답을 모르는 검증기: '정답:' 줄 · 답이 자료 · 그래프 집계(합)에 있나 · 생각의 각 문장의 조문 번호 · 수가 자료에서 왔나(과정 채점) · LLM 판정",
            "검증기마다 맞은 · 틀린 풀이를 가르는 AUROC · 0.5 기준 정확도와 그 검증기로 골랐을 때의 정답률",
        ],
        plans=[],
        docs=[
            (
                "추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측",
                "docs/stages/reasoning/rs1-budget/reasoning.md",
            ),
            ("추론 모델 · 테스트 시간 연산 맵", "docs/maps/reasoning.md"),
        ],
    ),
    Stage(
        key="rs_trace",
        pages=[
            Page(
                "rs_trace",
                "/reasoning/trace",
                "생각 과정 검사 · 추론 증류",
                "생각-답 불일치 · 근거 밖 주장 · 개인정보 · 지시 따르기, SFT 데이터",
                "reasoning/trace.html",
            )
        ],
        no="RS5",
        title="생각 과정 검사",
        short="생각 검사",
        en="Reasoning trace audit",
        status=DONE,
        flow="reasoning",
        map="reasoning",
        builds_on=["gr_output"],
        summary="생각과 답이 맞는지, 생각에 근거 밖 사실 · 개인정보가 없는지 본다",
        principle="생각 과정 검사는 생각 글을 출력처럼 다루는 것입니다. 생각의 결론과 답이 다르거나, 생각에만 나온 근거 밖 사실 · 개인정보 · 숨은 지시 따르기를 찾습니다.",
        why="생각 글을 사용자에게 보여 주거나 기록하면 그것도 출력입니다. 생각에서 한 계산과 답의 숫자가 다르면 답을 믿을 수 없습니다.",
        how=[
            "(기반) 출력 검사 · 개인정보(G4 · G2) · 입력 방어(G1)",
            "생각마다: 생각의 결론과 최종 답 불일치 · 자료에 없는 조문 번호 · 수 · 개인정보 · 인젝션 표현",
            "표시마다 표시된 풀이와 나머지의 정답률 — 검사가 쓸모 있는 신호인지",
        ],
        plans=[],
        docs=[
            (
                "추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측",
                "docs/stages/reasoning/rs1-budget/reasoning.md",
            ),
            ("추론 모델 · 테스트 시간 연산 맵", "docs/maps/reasoning.md"),
        ],
    ),
    Stage(
        key="rs_distill",
        pages=[Page("rs_distill", "/reasoning/trace#distill", "추론 증류 데이터", "맞은 풀이 → SFT 데이터")],
        no="RS6",
        title="추론 증류",
        short="추론 증류",
        en="Reasoning distillation",
        status=DONE,
        flow="reasoning",
        map="reasoning",
        builds_on=["distill", "pt_sft"],
        summary="큰 추론 모델의 풀이로 작은 모델을 학습해 싸게 생각하게 한다",
        principle="추론 증류는 큰 모델이 쓴 풀이(생각 + 답) 중 검증을 통과한 것만 모아 작은 모델을 SFT 하는 것입니다.",
        why="큰 추론 모델은 비싸고 느립니다. 자주 나오는 유형의 풀이를 작은 모델에 옮기면 같은 정확도를 싸게 얻을 수 있습니다.",
        how=[
            "(기반) 지식 증류(7a) · LoRA SFT(P3)",
            "학습 과제의 맞은 풀이(예산 강제 없음 · 선택: 검사 표시 없음) 중 생각이 가장 짧은 것 하나 → SFT 행, 생각 포함(풀이 증류) · 답만(답 증류)",
            "학습은 후학습 화면(LoRA SFT), 평가는 RLVR 평가(pt-번호)의 시험 과제로",
        ],
        plans=[],
        docs=[
            (
                "추론 모델 — 생각 예산 · 라우팅 · 여러 번 풀기 · 검증기 · 생각 검사 · 추론 증류 · 실측",
                "docs/stages/reasoning/rs1-budget/reasoning.md",
            ),
            ("추론 모델 · 테스트 시간 연산 맵", "docs/maps/reasoning.md"),
        ],
    ),
]
