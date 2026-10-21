"""평가 · 관측 (LLMOps) 맵 — 맵 정의와 단계. 화면 · 메뉴 · 문서가 모두 여기서 나온다(scripts/gen_docs.py)."""

from app.stages.registry.model import DONE, Map, Page, Stage

MAP = Map("evalops", "평가 · 관측 (LLMOps) 맵", "/maps/evalops", "docs/maps/evalops.md",
        summary="평가 세트 → 오프라인 평가 · 회귀 → 트레이싱 → 피드백 → 드리프트 감지 · A/B → 개선 반영 — 서비스가 지금 잘 되고 있는지 숫자로 아는 흐름",
        diagram="[평가 세트 · 정답] → [오프라인 평가 · 회귀] → [트레이싱]\n"
                "                                      ↓\n"
                "[비용 · 지연 대시보드] · [사용자 피드백 · 사람 판정] · [드리프트 감지] · [A/B 실험]\n"
                "                                      ↓\n"
                "                         [개선 반영 루프 (평가 세트 · 학습 데이터로)]",
        lead="모든 맵의 개선은 '좋아졌다'를 숫자로 확인할 때만 의미가 있습니다. 이 맵은 평가 세트를 관리하고, 바꿀 때마다 회귀를 확인하고, 서비스 중의 질문 · 단계 · 시간 · 비용을 기록하고, "
             "사람 피드백과 분포 변화를 모아 다시 평가 세트와 학습 데이터로 돌려보내는 흐름입니다. 실측에서 결론이 바뀐 이유가 대부분 측정 방법(프롬프트 캐시 · 비교 지표 · 판정 기준)이었습니다.",
        groups=(("만들고 재기", ("ev_sets", "ev_offline", "ev_tracing")),
                ("서비스 중에 보기", ("ev_cost", "ev_feedback", "ev_drift", "ev_ab")),
                ("되돌려 고치기", ("ev_loop",))),
        principles=("비교 측정은 같은 질문 · 같은 근거 · 같은 캐시 조건으로 — llama-server 프롬프트 캐시로 한 모델만 빨라 보인 사례(Q4 6초)",
                    "비교 지표를 단계에 맞게 — RAG vs 에이전트는 첫 검색이 같아 nDCG 차이가 늘 0, 답변 품질로 비교해야 차이가 보였다",
                    "자동 판정은 사람 판정으로 보정 — 판정 기준(근거 일치 vs 질문 관련성)을 먼저 확인한다",
                    "질문별 기록을 남긴다 — 평균만 있으면 '왜 나빠졌는지'(에이전트 20분 질문)를 찾을 수 없었다",
                    "질문이 적으면 '불확실'로 적는다 — 24 · 40문항 측정 대부분이 신뢰구간이 겹쳤다"),
        example="sentence-transformers 를 올린 날: 호환성 점검 → 고정 회귀 세트(법률 #5 · #7) 재실행 → 기준선 대비 nDCG · 근거 인용 차이가 유의하게 떨어지면 경보 → 질문별 기록에서 떨어진 유형(예: 여러 문서) 확인.")  # fmt: skip

STAGES: list[Stage] = [
    Stage(
        key="ev_sets",
        pages=[
            Page(
                "evalops_sets", "/evalops/sets", "평가 세트 · 회귀", "세트 버전 · 검토 상태 · 회귀 기준선 · 회귀 실행", "evalops/sets.html"
            )
        ],
        no="E1",
        title="평가 세트 · 정답 관리",
        short="평가 세트",
        en="Eval datasets & ground truth",
        status=DONE,
        flow="evalops",
        map="evalops",
        builds_on=["rag"],
        summary="질문 · 정답 근거 · 질문 유형을 세트로 관리하고, 생성 · 보정 · 보충 기록을 남긴다",
        principle="평가 세트는 '좋은 답'의 기준입니다. 질문마다 정답 문서 · 근거 문장 · 유형(사실 · 조건 · 여러 문서 · 답 없음 …)을 두고, 세트를 만든 방법 · 시드 · 보정 내역을 함께 남겨 같은 세트로 다시 잴 수 있게 합니다.",
        why="기준이 흔들리면 모든 비교가 무의미합니다. 생성 LLM 이 근거를 고치거나(법률 6%) 특정 종류가 빠지는(법령 질문 0개) 문제는 세트를 열어 봐야 보입니다.",
        how=[
            "세트 버전 · 변경 이력(문항 추가 · 검토마다 버전 +1)",
            "문항 검토 상태(검토 전 · 통과 · 제외) — 제외 문항은 평가에서 빠짐",
            "회귀 세트 지정 · 기준선 저장",
            "(있음) LLM 질문 7유형 생성 · 직접 입력 · 문서 지정 보충, 근거 보정 기록",
        ],
        plans=["검토 일괄 처리"],
        docs=[
            ("평가 세트 관리 · 회귀 평가", "docs/stages/evalops/e1-sets/regression.md"),
            ("평가 · 관측 (LLMOps) 맵", "docs/maps/evalops.md"),
        ],
    ),
    Stage(
        key="ev_offline",
        pages=[Page("evalops_regression", "/evalops/sets#regression", "회귀 실행", "기준선 대비 짝지은 차이 · 경보")],
        no="E2",
        title="오프라인 평가 · 회귀",
        short="회귀 평가",
        en="Offline eval & regression",
        status=DONE,
        flow="evalops",
        map="evalops",
        builds_on=["rag", "routing"],
        summary="설정 · 모델 · 라이브러리를 바꿀 때마다 고정 세트로 다시 재서 기준선보다 나빠졌는지 확인한다",
        principle="회귀 평가는 같은 세트 · 같은 조건으로 '바꾸기 전'과 '바꾼 뒤'를 짝지어 비교하는 것입니다. 질문별 차이의 신뢰구간으로 우연인지 판단하고, 유의하게 나빠지면 경보를 냅니다.",
        why="라이브러리 업그레이드 · 모델 교체 · 프롬프트 수정은 조용히 품질을 떨어뜨립니다. 사람이 매번 기억해서 재는 대신 정해진 세트를 자동으로 돌려야 합니다.",
        how=[
            "기준선 대비 질문별 짝지은 차이 · 95% 구간 → 유의하게 나빠지면 경보, 유형별 차이 · 가장 나빠진 질문",
            "설정을 바꿔 돌리기 · 라이브러리 업그레이드 감지 때 자동 실행(REGRESSION_ON_UPGRADE) · 정기 점검(WATCH_REGRESSION_HOURS)과 경보",
            "(있음) 조합 평가 · 연결 비교 · 라우팅 평가, 모델 호환성 점검",
        ],
        plans=["답변 품질 회귀(LLM 판정)"],
        docs=[
            ("평가 세트 관리 · 회귀 평가", "docs/stages/evalops/e1-sets/regression.md"),
            ("평가 · 관측 (LLMOps) 맵", "docs/maps/evalops.md"),
        ],
    ),
    Stage(
        key="ev_tracing",
        pages=[
            Page(
                "evalops_traces",
                "/evalops/traces",
                "요청 기록 · 비용",
                "질문별 단계 · 시간 · 토큰 · 비용, 느린 · 근거 약한 답 찾기",
                "evalops/traces.html",
            )
        ],
        no="E3",
        title="트레이싱",
        short="트레이싱",
        en="Tracing",
        status=DONE,
        flow="evalops",
        map="evalops",
        builds_on=["rag", "agent"],
        summary="질문마다 단계 · 시간 · 토큰 · 결정(라우팅 · 도구)을 기록해 한 요청을 끝까지 따라가 본다",
        principle="트레이스는 요청 하나가 거친 단계(검색 · 재정렬 · 라우팅 · 에이전트 행동 · 답변 · 검증)를 시간 순서로 남긴 기록입니다. 단계마다 입력 · 출력 요약 · 시간 · 토큰을 남기면 느리거나 틀린 원인을 찾을 수 있습니다.",
        why="평균만 있으면 원인을 못 찾습니다 — 에이전트 측정에서 한 질문이 20분 걸린 이유를 질문별 기록이 없어 찾지 못했습니다.",
        how=[
            "모든 서비스 답변을 요청 기록으로: 단계별 시간(입력 검사 · 검색 · 근거 검사 · LLM · 검증 · 출력 검사) · 토큰 · 검색 신호(1위 점수 · 1 · 2위 차) · 근거 · 검증 · 가드레일 결과",
            "기록 목록 · 상세, 느림 · 근거 약함 · 거절 · 차단 표시로 찾기",
        ],
        plans=["에이전트 · 연결 실행 단계도 기록"],
        docs=[
            ("요청 기록 · 비용 · 지연", "docs/stages/evalops/e3-tracing/tracing.md"),
            ("평가 · 관측 (LLMOps) 맵", "docs/maps/evalops.md"),
        ],
    ),
    Stage(
        key="ev_cost",
        pages=[Page("evalops_cost", "/evalops/traces#dashboard", "비용 · 지연 대시보드", "p50 · p95 지연 · 토큰 · 비용")],
        no="E4",
        title="비용 · 지연 대시보드",
        short="비용 · 지연",
        en="Cost & latency dashboard",
        status=DONE,
        flow="evalops",
        map="evalops",
        builds_on=["quant", "routing"],
        summary="질문당 토큰 · 시간 · 비용을 모아 단계별 · 경로별로 보여 준다",
        principle="답변 하나의 비용은 읽은 토큰 · 쓴 토큰 · 모델 단가 · 걸린 시간의 합입니다. 단계 · 경로 · 모델별로 나눠 모으면 어디에 돈과 시간이 쓰이는지 보입니다.",
        why="라우팅 · 압축 · 소형 모델의 효과는 '얼마나 아꼈나'로 판단합니다. 지금은 측정 때만 시간을 보고, 서비스 중의 분포(p95)는 모릅니다.",
        how=[
            "기간 · 경로 · 모델 · 종류별 p50 · p95 지연, 토큰, 비용(LLM_PRICES: 1M 토큰당 가격), 단계별 시간 몫",
        ],
        plans=["예산 경보"],
        docs=[
            ("요청 기록 · 비용 · 지연", "docs/stages/evalops/e3-tracing/tracing.md"),
            ("평가 · 관측 (LLMOps) 맵", "docs/maps/evalops.md"),
        ],
    ),
    Stage(
        key="ev_feedback",
        pages=[
            Page(
                "evalops_feedback",
                "/evalops/feedback",
                "피드백 · 개선 루프",
                "좋아요 · 싫어요 · 이유, 실패 유형 분류 → 평가 세트 · 학습 데이터",
                "evalops/feedback.html",
            )
        ],
        no="E5",
        title="사용자 피드백 · 사람 판정",
        short="피드백",
        en="User feedback & human labels",
        status=DONE,
        flow="evalops",
        map="evalops",
        builds_on=["rag", "rl"],
        summary="답변마다 좋아요 · 싫어요 · 이유를 받고, 사람 판정으로 자동 판정을 보정한다",
        principle="사용자 피드백은 가장 싼 정답 신호지만 시끄럽습니다. 이유(근거 없음 · 질문과 상관없음 · 틀린 숫자)를 고르게 하면 어느 단계를 고칠지 알 수 있고, 사람 판정과 자동 판정의 일치도로 자동 판정 기준을 맞춥니다.",
        why="자동 판정만 믿으면 틀립니다 — 작은 LLM 판정은 사람 판정 28개를 모두 통과시켰고, 사람이 문제 삼은 것은 '질문과 상관없는 문장'이었습니다.",
        how=[
            "답변마다 좋아요 · 싫어요 + 이유 · 메모(답변 화면 · 기록 화면)",
            "자동 판정(근거 일치)과 사람 판정의 일치율",
            "싫어요 받은 기록 → 평가 세트 후보",
        ],
        plans=["판정자 여럿 · 합의"],
        docs=[
            ("사용자 피드백 · 개선 루프", "docs/stages/evalops/e5-feedback/feedback.md"),
            ("평가 · 관측 (LLMOps) 맵", "docs/maps/evalops.md"),
        ],
    ),
    Stage(
        key="ev_drift",
        pages=[
            Page(
                "evalops_drift",
                "/evalops/drift",
                "드리프트 감지",
                "기준 기간과 최근 질문 분포 · 검색 신호 비교, 새 유형 질문",
                "evalops/drift.html",
            )
        ],
        no="E6",
        title="드리프트 · 이상 감지",
        short="드리프트",
        en="Drift & anomaly detection",
        status=DONE,
        flow="evalops",
        map="evalops",
        builds_on=["apps"],
        summary="들어오는 질문의 분포 · 검색 확신도 · 거절률이 평소와 달라지면 알린다",
        principle="드리프트는 시간이 지나며 질문 주제 · 말투가 바뀌거나 자료가 낡아 성능이 떨어지는 현상입니다. 질문 임베딩의 분포, 검색 확신도, 거절률 같은 신호를 기준 기간과 비교해 감지합니다.",
        why="평가 세트는 만든 시점의 질문만 담습니다. 새 제품 · 새 법령이 나오면 세트에 없는 질문이 늘어 품질이 떨어지는데, 평가 세트로는 보이지 않습니다.",
        how=[
            "기준 기간 vs 최근: 질문 임베딩으로 새 유형 질문(가장 가까운 기준 질문 유사도 < 0.6) 비율 · 묶음",
            "검색 신호(1위 점수 · 1 · 2위 차) 변화를 부트스트랩 구간으로 — 우연한 흔들림과 구분",
            "정기 점검(WATCH_DRIFT_HOURS): 주기마다 최근 7일 vs 30일을 다시 재고, 경보가 나면 화면 · ALERT_WEBHOOK 으로",
            "새 유형 질문 묶음을 평가 세트 후보(정답 문서 없이 검토 전)로 바로 보내기",
        ],
        plans=["새 유형 묶음에 정답 문서 후보 자동 제안(검색 상위)"],
        docs=[("드리프트 감지", "docs/stages/evalops/e6-drift/drift.md"), ("평가 · 관측 (LLMOps) 맵", "docs/maps/evalops.md")],
    ),
    Stage(
        key="ev_ab",
        pages=[
            Page(
                "evalops_experiments",
                "/evalops/experiments",
                "A/B 실험",
                "사용자를 나눠 두 설정 비교, 기록 재생으로 미리 재기",
                "evalops/experiments.html",
            )
        ],
        no="E7",
        title="A/B · 온라인 실험",
        short="A/B 실험",
        en="A/B & online experiments",
        status=DONE,
        flow="evalops",
        map="evalops",
        builds_on=["routing"],
        summary="실제 요청을 두 설정에 나눠 보내 품질 · 만족도 · 비용을 비교한다",
        principle="A/B 실험은 요청을 무작위로 나눠 두 설정에 보내고 결과를 비교합니다. 오프라인 평가가 '세트에서 좋은가'라면 A/B 는 '실제 사용자에게 좋은가'를 봅니다.",
        why="오프라인 지표와 실제 만족도는 어긋날 수 있습니다(Best-of 는 보상이 유의하게 올랐지만 품질은 불확실). 출시 결정은 실제 요청으로 확인해야 합니다.",
        how=[
            "실험 = 두 설정(검색 · LLM). 사용자 해시로 고정 배정(같은 사용자는 늘 같은 쪽), 실험 답변도 서비스 답변으로 기록",
            "기록 재생: 지난 질문을 두 설정으로 다시 답해 출시 전에 비교",
            "판정: 근거 일치 · 좋아요 비율 · 지연 차이와 표본 수",
        ],
        plans=["순차 검정(일찍 멈추기)"],
        docs=[("A/B 실험", "docs/stages/evalops/e7-ab/ab.md"), ("평가 · 관측 (LLMOps) 맵", "docs/maps/evalops.md")],
    ),
    Stage(
        key="ev_loop",
        pages=[Page("evalops_loop", "/evalops/feedback#loop", "개선 루프", "실패 유형 → 평가 세트 · 빈틈 CSV")],
        no="E8",
        title="개선 반영 루프",
        short="개선 루프",
        en="Improvement loop",
        status=DONE,
        flow="evalops",
        map="evalops",
        builds_on=["finetune", "rl"],
        summary="실패 사례를 모아 평가 세트 · 학습 데이터 · 규칙으로 되돌려 다음 버전을 만든다",
        principle="개선 루프(데이터 플라이휠)는 서비스에서 나온 실패 사례를 분류해 평가 세트(재발 방지), 학습 데이터(파인튜닝 · 선호 학습), 규칙(라우팅 · 가드레일)으로 돌려보내는 과정입니다.",
        why="같은 실수를 사람이 매번 찾지 않으려면 실패가 자동으로 다음 평가 · 학습의 재료가 되어야 합니다.",
        how=[
            "실패 유형 분류(검색 실패 · 인용 문제 · 질문과 다름 · 과잉 거절 · 정책) — 기록의 검증 · 피드백 신호로",
            "평가 세트로 보내기 · 빈틈 목록 CSV(학습 데이터 후보)",
        ],
        plans=["분류별 자동 개선 제안"],
        docs=[
            ("사용자 피드백 · 개선 루프", "docs/stages/evalops/e5-feedback/feedback.md"),
            ("평가 · 관측 (LLMOps) 맵", "docs/maps/evalops.md"),
        ],
    ),
]
