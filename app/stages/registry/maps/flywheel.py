"""데이터 플라이휠 맵 — 맵 정의와 단계. 화면 · 메뉴 · 문서가 모두 여기서 나온다(scripts/gen_docs.py)."""

from app.stages.registry.model import DONE, Map, Page, Stage

MAP = Map('flywheel', '데이터 플라이휠 맵', "/maps/flywheel", "docs/maps/flywheel.md",
        summary='서비스 로그 → 실패 분류 → 사람 검토 → 평가 · 학습 데이터 → 재학습 → 게이트 → 단계적 배포 → 다시 로그 — 평가 · 후학습 · 서빙 · 가드레일을 하나의 순환으로',
        diagram='[서비스 로그] → [실패 자동 분류] → [사람 검토 우선순위]\n        ↑                                   ↓\n[단계적 배포 · 롤백] ← [회귀 · 안전성 게이트] ← [재학습 · 재색인] ← [평가 세트 · 학습 데이터]',
        lead='평가 · 관측 맵과 후학습 맵이 한 방향의 흐름이라면, 플라이휠은 그것을 순환으로 묶습니다. 서비스에서 실패가 나오면 자동으로 분류되고, 사람이 가장 가치 있는 사례부터 검토해, 평가 세트와 학습 데이터가 되고, 재학습한 모델은 같은 조건의 게이트를 통과해야 일부 사용자부터 배포됩니다. 순환이라 한 단계를 바꾸면 다른 단계의 지표가 움직입니다 — 그래서 한 번에 하나씩 바꾸고 기록합니다.',
        groups=(('모으기', ('fw_logs', 'fw_triage', 'fw_review')), ('만들기', ('fw_assets', 'fw_retrain')), ('내보내기', ('fw_gate', 'fw_rollout'))),
        principles=('평가 세트와 학습 데이터를 섞지 않는다 — 누수 방지(여러 근거 모두 제외)를 순환 전체에 적용', '피드백은 편향된다 — 불만이 있는 사용자만 누르므로 실패 분류 · 무작위 표본 검토로 보정', '게이트는 같은 조건으로 — 프롬프트 캐시 · 세트 버전 · 시드를 맞춘 회귀 평가만 통과 기준으로', '한 번에 하나씩 바꾼다 — 순환에서는 모델 · 청킹 · 프롬프트를 같이 바꾸면 무엇이 효과였는지 알 수 없다', "적은 라벨로 결론 내지 않는다 — 학습 라우터는 '어려움' 라벨 5개로 지연 −25% 였지만 기준값 하나 차이로 품질이 흔들렸다"),
        example="법률 서비스에서 '답 없는 질문을 지어내 답함'이 반복 → 실패 분류가 '거절 실패'로 묶음 → 검토 화면에 우선 표시 → 사람이 확인한 20건을 평가 세트(재발 방지)와 DPO 쌍(거절 vs 지어낸 답)으로 → 재학습 → 법률 회귀 세트 · 레드팀 게이트 통과 → 10% 사용자에게 배포 → 거절률 · 만족도 확인 후 전체로.")  # fmt: skip

STAGES: list[Stage] = [
    Stage(
        key="fw_logs",
        pages=[
            Page(
                "fw_triage", "/flywheel/triage", "실패 분류 · 처방", "서비스 로그 · 실패 유형 추이 · 싼 것부터 처방", "flywheel/triage.html"
            )
        ],
        no="FW1",
        title="서비스 로그 수집",
        short="로그",
        en="Production logs",
        status=DONE,
        flow="flywheel",
        map="flywheel",
        builds_on=["ev_tracing"],
        summary="질문 · 단계 · 근거 · 답변 · 검증 결과 · 피드백을 요청마다 남겨 순환의 원료로 쓴다",
        principle="플라이휠의 원료는 서비스 기록입니다. 요청마다 질문 · 사용한 설정 버전 · 근거 · 답변 · 검증 점수 · 사용자 피드백을 한 묶음으로 남겨야, 나중에 실패를 분류하고 다시 재현할 수 있습니다.",
        why="기록이 측정 때만 있으면 실제 사용자 질문의 분포 · 실패를 모릅니다. 평가 세트가 실제와 멀어지는 원인입니다.",
        how=[
            "서비스 답변(RAG · AS · 대화 · GraphRAG · A2A · 멀티에이전트 · 업무)의 요청 기록을 원료로 — 종류별 수 · 보관 기한까지 한 화면에",
            "배포 중인 버전이 있으면 요청 기록 signals.version 으로 어느 버전의 답인지 남김",
        ],
        plans=[],
        docs=[
            ("데이터 플라이휠 — 실패 분류 · 검토 · 분배 · 처방 · 게이트 · 단계적 배포 · 실측", "docs/stages/flywheel/fw1-logs/flywheel.md"),
            ("데이터 플라이휠 맵", "docs/maps/flywheel.md"),
        ],
    ),
    Stage(
        key="fw_triage",
        pages=[Page("fw_triage_c", "/flywheel/triage#triage", "실패 자동 분류", "유형 · 날짜별 추이")],
        no="FW2",
        title="실패 자동 분류",
        short="실패 분류",
        en="Failure triage",
        status=DONE,
        flow="flywheel",
        map="flywheel",
        builds_on=["ev_loop", "critic_agent"],
        summary="실패를 검색 실패 · 인용 실패 · 질문과 상관없는 답 · 거절 실패 · 형식 오류로 자동 분류한다",
        principle="검증 점수와 피드백으로 실패 유형을 나눕니다 — 정답 근거가 검색되지 않음(검색), 검색됐지만 인용 안 함(답변), 근거에 있지만 질문과 상관없음(관련성), 답 없는 질문에 답함(거절). 유형마다 고칠 곳이 다릅니다.",
        why="실패를 한 덩어리로 보면 '모델을 바꾸자'로만 이어집니다. 법률 실측에서 RAG 의 실패는 검색(56%)이었고, 에이전트의 실패는 같은 검색 결과에서 인용을 덜 한 것이었습니다 — 원인이 달랐습니다.",
        how=[
            "개선 루프(E8)의 분류(검색 · 인용 · 상관없는 답 · 과도한 거절 · 정책)를 그대로 쓰고 형식 오류 · 확신도 낮은데 답함을 더함 — 같은 실패를 두 곳이 다르게 세지 않게",
            "유형별 날짜 추이(차트 · 표)와 예",
        ],
        plans=[],
        docs=[
            ("데이터 플라이휠 — 실패 분류 · 검토 · 분배 · 처방 · 게이트 · 단계적 배포 · 실측", "docs/stages/flywheel/fw1-logs/flywheel.md"),
            ("데이터 플라이휠 맵", "docs/maps/flywheel.md"),
        ],
    ),
    Stage(
        key="fw_review",
        pages=[
            Page(
                "fw_review", "/flywheel/review", "검토 · 자산 분배", "검토 우선순위 · 평가 / 학습 분배 · 누수 검사", "flywheel/review.html"
            )
        ],
        no="FW3",
        title="사람 검토 우선순위",
        short="검토 우선순위",
        en="Review prioritization (active learning)",
        status=DONE,
        flow="flywheel",
        map="flywheel",
        builds_on=["ev_feedback"],
        summary="사람의 검토 시간을 가장 배울 것이 많은 사례(자동 판정이 애매한 것 · 새 유형)에 먼저 쓴다",
        principle="능동 학습은 모델이 가장 헷갈리는 사례(점수가 기준값 근처)와 대표성 있는 표본을 골라 사람에게 먼저 보여 주는 방법입니다. 같은 라벨 수로 더 많이 배웁니다.",
        why="사람 판정은 비쌉니다 — 이 프로젝트에서 판정 28개로 검증 기준을 처음 맞췄습니다. 무작위로 고르면 쉬운 사례에 시간을 씁니다.",
        how=[
            "검토 순서: 싫어요 > 근거 일치 0.5~0.7(자동으로 못 가름) > 실패 분류 > 확신도 낮음, 20%는 무작위 표본(규칙 밖 실패를 찾으려고), 같은 질문은 한 번",
            "판정(맞음 · 틀림) · 유형 · 정답 문서 · 고친 답을 기록(fw_reviews, 마이그레이션 0016)",
        ],
        plans=[],
        docs=[
            ("데이터 플라이휠 — 실패 분류 · 검토 · 분배 · 처방 · 게이트 · 단계적 배포 · 실측", "docs/stages/flywheel/fw1-logs/flywheel.md"),
            ("데이터 플라이휠 맵", "docs/maps/flywheel.md"),
        ],
    ),
    Stage(
        key="fw_assets",
        pages=[Page("fw_assets", "/flywheel/review#assets", "평가 · 학습 데이터로", "분배 · 누수 방지")],
        no="FW4",
        title="평가 세트 · 학습 데이터로 변환",
        short="자산화",
        en="Turn reviews into assets",
        status=DONE,
        flow="flywheel",
        map="flywheel",
        builds_on=["ev_sets", "pt_select"],
        summary="검토한 사례를 평가 세트(재발 방지)와 학습 데이터(교정)로 나눠 보내고, 둘이 섞이지 않게 한다",
        principle="같은 실패 사례를 평가 세트와 학습 데이터 양쪽에 넣으면 평가가 부풀려집니다. 사례를 나눠 보내고, 평가 세트에 들어간 사례의 근거 지문은 학습에서 뺍니다.",
        why="순환에서는 누수가 쉽게 생깁니다 — 어제 학습한 사례로 오늘 평가하면 개선이 아니라 암기를 잽니다.",
        how=[
            "평가로: 컬렉션의 '플라이휠 회귀 후보' 평가 세트에 정답 문서와 함께(정답 없으면 막음), 학습으로: 학습 데이터 JSONL(질문 · 고친 답 · 정답 문서)",
            "반대쪽에 같은 · 아주 비슷한 질문(글자 바이그램 겹침 0.8 이상)이 있으면 누수로 막고 이유를 남김",
        ],
        plans=[],
        docs=[
            ("데이터 플라이휠 — 실패 분류 · 검토 · 분배 · 처방 · 게이트 · 단계적 배포 · 실측", "docs/stages/flywheel/fw1-logs/flywheel.md"),
            ("데이터 플라이휠 맵", "docs/maps/flywheel.md"),
        ],
    ),
    Stage(
        key="fw_retrain",
        pages=[Page("fw_retrain", "/flywheel/triage#retrain", "재학습 · 재색인 처방", "실패 유형 → 싼 것부터")],
        no="FW5",
        title="재학습 · 재색인",
        short="재학습",
        en="Retrain & reindex",
        status=DONE,
        flow="flywheel",
        map="flywheel",
        builds_on=["finetune", "rag"],
        summary="고칠 곳에 따라 임베딩 재학습 · 재색인 · 프롬프트 · LLM 후학습 중 가장 싼 것부터 한다",
        principle="실패 유형에 따라 처방이 다릅니다 — 검색 실패는 청킹 · 임베딩 파인튜닝 · 재색인, 인용 · 관련성 실패는 프롬프트 · LLM 후학습, 거절 실패는 선호 학습. 가장 싼 처방부터 시도합니다.",
        why="모델 재학습은 비싸고 느립니다. 프롬프트 규칙 하나(답변 규칙 5번)나 규칙 기반 도구 선택(번호 조회)으로 해결되는 경우가 많았습니다.",
        how=[
            "실패 유형 분포 → 고칠 곳을 싼 것부터: 설정 · 규칙 → 사람 검토 · 평가 세트 → 자료 · 재색인 → 임베딩 재학습 · LLM 후학습, 각 처방은 그 화면으로 연결"
        ],
        plans=[],
        docs=[
            ("데이터 플라이휠 — 실패 분류 · 검토 · 분배 · 처방 · 게이트 · 단계적 배포 · 실측", "docs/stages/flywheel/fw1-logs/flywheel.md"),
            ("데이터 플라이휠 맵", "docs/maps/flywheel.md"),
        ],
    ),
    Stage(
        key="fw_gate",
        pages=[
            Page(
                "fw_release",
                "/flywheel/release",
                "게이트 · 단계적 배포",
                "버전 · 회귀 · 레드팀 게이트 · 비율 배포 · 롤백",
                "flywheel/release.html",
            )
        ],
        no="FW6",
        title="회귀 · 안전성 게이트",
        short="게이트",
        en="Regression & safety gate",
        status=DONE,
        flow="flywheel",
        map="flywheel",
        builds_on=["ev_offline", "gr_redteam"],
        summary="새 버전은 고정 회귀 세트 · 레드팀 세트를 같은 조건으로 통과해야 배포 후보가 된다",
        principle="게이트는 '나빠지지 않았음'을 확인하는 자동 관문입니다. 도메인 회귀 세트 · 일반 능력 · 공격 세트를 같은 조건(캐시 · 시드 · 세트 버전)으로 돌려, 유의한 하락이 없을 때만 통과시킵니다.",
        why="순환이 빨라질수록 사람이 매번 확인할 수 없습니다. 게이트 없이 자동 재학습을 돌리면 조용한 품질 하락이 쌓입니다.",
        how=[
            "바꾼 것(검색 설정 · 방어 모드 · LLM)을 버전(fw_versions)으로, 게이트 = 회귀 세트마다 기준선과 같은 질문으로 짝 비교(nDCG −0.02 · hit@5 −0.03 까지 허용, 유의한 하락이면 막음) + 같은 공격의 레드팀(같은 방어 모드의 최근 결과보다 떨어지면 막음)",
            "평균이 올라도 한 세트 · 한 공격 유형이 떨어지면 통과하지 못함",
        ],
        plans=[],
        docs=[
            ("데이터 플라이휠 — 실패 분류 · 검토 · 분배 · 처방 · 게이트 · 단계적 배포 · 실측", "docs/stages/flywheel/fw1-logs/flywheel.md"),
            ("데이터 플라이휠 맵", "docs/maps/flywheel.md"),
        ],
    ),
    Stage(
        key="fw_rollout",
        pages=[Page("fw_rollout", "/flywheel/release#rollout", "단계적 배포 · 롤백", "5 → 25 → 50 → 100% · 자동 롤백")],
        no="FW7",
        title="단계적 배포 · 롤백",
        short="단계적 배포",
        en="Staged rollout & rollback",
        status=DONE,
        flow="flywheel",
        map="flywheel",
        builds_on=["ev_ab"],
        summary="게이트를 통과한 버전을 일부 사용자부터 내보내고, 지표가 나빠지면 즉시 이전 버전으로 되돌린다",
        principle="단계적 배포(카나리)는 새 버전을 5% → 25% → 100% 로 넓히며 실제 지표(피드백 · 거절률 · 지연)를 비교하는 것입니다. 나빠지면 버전 하나만 바꿔 되돌립니다.",
        why="오프라인 게이트를 통과해도 실제 사용자에게는 나쁠 수 있습니다(보상과 품질이 어긋난 Best-of 처럼).",
        how=[
            "연결 계층의 기본 검색 설정이 배포 중인 버전을 요청의 pct% 에 — AS · 대화 · 답변이 함께 바뀜(요청마다 무작위)",
            "같은 기간 후보 팔 vs 나머지의 근거 일치 · 거절률 · 싫어요를 비교(후보 20건 이상), 나빠지면 롤백(FLYWHEEL_WATCH_HOURS 면 자동) · 좋으면 다음 비율, 100% 다음은 현재 버전으로 승격",
        ],
        plans=["사용자 단위로 나누기(같은 사용자는 같은 버전)"],
        docs=[
            ("데이터 플라이휠 — 실패 분류 · 검토 · 분배 · 처방 · 게이트 · 단계적 배포 · 실측", "docs/stages/flywheel/fw1-logs/flywheel.md"),
            ("데이터 플라이휠 맵", "docs/maps/flywheel.md"),
        ],
    ),
]
