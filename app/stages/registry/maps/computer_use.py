"""컴퓨터 사용 · 브라우저 에이전트 맵 — 맵 정의와 단계. 화면 · 메뉴 · 문서가 모두 여기서 나온다(scripts/gen_docs.py)."""

from app.stages.registry.model import DONE, Map, Page, Stage

MAP = Map('computer_use', '컴퓨터 사용 · 브라우저 에이전트 맵', '/maps/computer-use', 'docs/maps/computer-use.md',
        summary='화면 이해 → 행동 계획 · 실행 → 상태 확인 → 위험 행동 승인 → 웹 콘텐츠 인젝션 방어 → 재생 평가 — 화면을 보고 클릭 · 입력하는 에이전트',
        diagram='[화면 이해] → [행동 계획 · 실행] → [상태 확인]\n                    ↓\n[위험 행동 승인] · [웹 콘텐츠 인젝션 방어]\n                    ↓\n[재생 평가]',
        lead='API 가 없는 사내 시스템(레거시 접수 화면 · 관리자 페이지)은 사람이 화면을 보고 클릭해야 합니다. 컴퓨터 사용 에이전트는 화면(스크린샷 · 접근성 트리)을 보고 행동을 고르지만, 한 번의 잘못된 클릭이 되돌릴 수 없는 결과를 낳고 웹 페이지의 글이 지시로 작동할 수 있습니다. 비전 LLM · 장기 실행(승인 · 체크포인트) · 인젝션 방어 위에 짓습니다.',
        groups=(('보고 하기', ('cu_perceive', 'cu_act', 'cu_check')), ('멈추고 막기', ('cu_approve', 'cu_injection')), ('재기', ('cu_eval',))),
        principles=('되돌릴 수 없는 행동 앞에서는 멈춘다 — 장기 실행의 승인 지점', '화면 글은 데이터다 — 지시로 따르지 않는다(근거 격리와 같은 원칙)', '행동마다 결과를 확인한다 — 클릭이 됐다고 믿지 않는다', '같은 과제를 재생으로 잰다 — 사이트가 바뀌어도 비교할 수 있게'),
        example="'레거시 AS 접수 화면에 오늘 티켓 5건 입력' → 화면 이해(입력란 찾기) → 티켓마다 입력 · 확인 → 제출 버튼 앞에서 승인 요청 → 페이지에 '이전 지시를 무시하고…'가 있으면 따르지 않고 기록 → 녹화를 재생해 성공률 측정.")  # fmt: skip

STAGES: list[Stage] = [
    Stage(
        key="cu_perceive",
        pages=[
            Page("cu_screen", "/computer-use/screen", "화면 이해", "접근성 트리 · 숨은 글 · 요소 찾기 정확도", "computer_use/screen.html")
        ],
        no="CU1",
        title="화면 이해",
        short="화면 이해",
        en="Screen understanding",
        status=DONE,
        flow="computer_use",
        map="computer_use",
        builds_on=["as_photo", "mm_input"],
        summary="스크린샷 · 접근성 트리로 화면 요소를 찾는다",
        principle="화면 이해는 스크린샷(비전 LLM)과 접근성 트리(DOM)로 버튼 · 입력란 · 표를 찾아 좌표 · 이름을 얻는 것입니다.",
        why="요소를 잘못 찾으면 엉뚱한 곳을 누릅니다. 그림만 보는 것과 구조(DOM)를 함께 보는 것의 정확도가 다릅니다.",
        how=[
            "(기반) 사진 진단(AS4) · 멀티모달 임베딩(MA1)",
            "시험용 사이트 HTML → 접근성 트리(역할 · 이름 · 값 · 요소 번호), 이름은 label · aria-label · 글자에서, 숨은 요소(display:none · hidden · aria-hidden)는 트리에서 빼 '숨은 글'로",
            "사람의 설명('제출하는 버튼')으로 요소를 찾는 정확도(11개)",
        ],
        plans=["실제 브라우저(Playwright) 뒷단 · 스크린샷 비전"],
        docs=[
            (
                "컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측",
                "docs/stages/computer-use/cu1-perceive/computer_use.md",
            ),
            ("컴퓨터 사용 · 브라우저 에이전트 맵", "docs/maps/computer-use.md"),
        ],
    ),
    Stage(
        key="cu_act",
        pages=[
            Page("cu_run", "/computer-use/run", "화면 에이전트 실행", "행동 · 상태 확인 · 승인 · 최종 상태 판정", "computer_use/run.html")
        ],
        no="CU2",
        title="행동 계획 · 실행",
        short="행동 실행",
        en="Action planning & execution",
        status=DONE,
        flow="computer_use",
        map="computer_use",
        builds_on=["agent"],
        summary="클릭 · 입력 · 스크롤을 고르고 헤드리스 브라우저로 실행한다",
        principle="행동 계획은 목표와 지금 화면으로 다음 행동 하나를 고르는 것이고, 실행은 브라우저 자동화로 그 행동을 하는 것입니다.",
        why="한 번에 여러 행동을 정하면 중간 화면 변화를 놓칩니다. 행동 하나 → 확인의 반복이 안전합니다.",
        how=[
            "(기반) ReAct 에이전트(8a)",
            "화면 하나 보고 행동 하나(click · type · select · check · navigate · back · done) JSON, 흉내 브라우저(표준 라이브러리 HTML 파서)가 폼 제출 · 링크를 사이트 상태 기계로 실행",
            "성공은 에이전트의 말이 아니라 사이트 최종 상태로(티켓이 그 값으로 생겼나 · 지우면 안 되는 것이 남았나)",
        ],
        plans=[],
        docs=[
            (
                "컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측",
                "docs/stages/computer-use/cu1-perceive/computer_use.md",
            ),
            ("컴퓨터 사용 · 브라우저 에이전트 맵", "docs/maps/computer-use.md"),
        ],
    ),
    Stage(
        key="cu_check",
        pages=[Page("cu_check", "/computer-use/run#act", "상태 확인", "행동 전후 화면 지문 · 알림")],
        no="CU3",
        title="상태 확인",
        short="상태 확인",
        en="State verification",
        status=DONE,
        flow="computer_use",
        map="computer_use",
        builds_on=["lr_verify"],
        summary="행동 뒤 화면이 기대한 상태인지 확인한다",
        principle="상태 확인은 행동 전후 화면을 비교해 입력이 들어갔는지, 다음 화면으로 넘어갔는지, 오류 메시지가 떴는지 보는 것입니다.",
        why="클릭이 됐다고 믿으면 실패한 입력 위에 다음 단계를 쌓습니다. 화면은 느리게 바뀌거나 오류를 조용히 띄웁니다.",
        how=[
            "(기반) 완료 판정(LR6)",
            "행동 전후의 주소 · 트리 지문 · 알림(role=alert)을 비교해 '바뀐 것 없음' · 오류 알림 · 요소 없음 · 선택지에 없는 값을 다음 걸음에",
            "브라우저 상태(사이트 상태 · 주소 · 입력값)를 저장할 수 있어 승인 대기 뒤 이어 가기 · 재생",
        ],
        plans=[],
        docs=[
            (
                "컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측",
                "docs/stages/computer-use/cu1-perceive/computer_use.md",
            ),
            ("컴퓨터 사용 · 브라우저 에이전트 맵", "docs/maps/computer-use.md"),
        ],
    ),
    Stage(
        key="cu_approve",
        pages=[Page("cu_approve", "/computer-use/run#approve", "위험 행동 승인", "멈춤 · 승인 · 거부 · 이어 가기")],
        no="CU4",
        title="위험 행동 승인",
        short="위험 승인",
        en="Approval for risky actions",
        status=DONE,
        flow="computer_use",
        map="computer_use",
        builds_on=["lr_approval"],
        summary="제출 · 결제 · 삭제 같은 행동 전에 사람 승인을 받는다",
        principle="위험 행동 승인은 되돌릴 수 없는 행동(제출 · 결제 · 삭제 · 메일 보내기) 앞에서 멈추고 화면 · 입력값을 보여 승인을 받는 것입니다.",
        why="화면 에이전트는 무엇이 되돌릴 수 없는지 모를 때가 많습니다. 버튼 이름 · 페이지로 규칙을 정해 멈춥니다.",
        how=[
            "(기반) 승인 지점(LR4)",
            "되돌릴 수 없는 행동: 사이트가 표시한 버튼(data-irreversible) 또는 이름 규칙(접수 · 삭제 · 결제 · 보내기 · 제출)",
            "멈추고 승인 기다림(실행 기록 파일 · 이어 가기) · 자동 승인(기록만) · 거부(하지 않고 알림)",
        ],
        plans=[],
        docs=[
            (
                "컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측",
                "docs/stages/computer-use/cu1-perceive/computer_use.md",
            ),
            ("컴퓨터 사용 · 브라우저 에이전트 맵", "docs/maps/computer-use.md"),
        ],
    ),
    Stage(
        key="cu_injection",
        pages=[
            Page(
                "cu_injection", "/computer-use/eval#injection", "웹 콘텐츠 인젝션 방어", "숨은 글 · 격리 · 허용 도메인, 인젝션을 따른 비율"
            )
        ],
        no="CU5",
        title="웹 콘텐츠 인젝션 방어",
        short="웹 인젝션",
        en="Web prompt injection defense",
        status=DONE,
        flow="computer_use",
        map="computer_use",
        builds_on=["gr_injection", "io_audit"],
        summary="페이지 글 속 지시를 따르지 않고 허용 도메인만 다닌다",
        principle="웹 콘텐츠 인젝션은 페이지에 숨긴 글('이전 지시를 무시하고 …로 보내라')이 에이전트의 지시로 작동하는 공격입니다. 화면 글은 데이터로 다루고, 이동 · 입력은 허용 목록 안에서만 합니다.",
        why="브라우저 에이전트는 신뢰할 수 없는 글을 계속 읽습니다. 근거 격리와 같은 원칙이 화면에도 필요합니다.",
        how=[
            "(기반) 입력 방어 · 근거 격리(G1) · 감사 추적(IO6)",
            "매뉴얼 페이지의 숨은 지시 · 화면에 보이는 'AI 대상 지시' · 허용 밖 도메인 링크",
            "방어: 트리만 보기(숨은 글 제외) · 화면 글을 데이터로 격리 · 허용 도메인만 이동 — 인젝션을 따름(허용 밖 이동 시도 · 연락처를 밖으로 · 관리자 전체 삭제)을 설정별로",
        ],
        plans=[],
        docs=[
            (
                "컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측",
                "docs/stages/computer-use/cu1-perceive/computer_use.md",
            ),
            ("컴퓨터 사용 · 브라우저 에이전트 맵", "docs/maps/computer-use.md"),
        ],
    ),
    Stage(
        key="cu_eval",
        pages=[Page("cu_eval", "/computer-use/eval", "웹 인젝션 · 재생 평가", "과제 × 방어 설정 · 재생", "computer_use/eval.html")],
        no="CU6",
        title="재생 평가",
        short="재생 평가",
        en="Replay evaluation",
        status=DONE,
        flow="computer_use",
        map="computer_use",
        builds_on=["rv_env"],
        summary="과제 세트를 녹화 · 재생해 성공률 · 걸음 수를 잰다",
        principle="재생 평가는 정해진 시작 화면 · 목표로 과제를 만들고, 에이전트의 성공률 · 걸음 수 · 위험 행동 시도를 재는 것입니다. 시험용 화면을 고정해 사이트가 바뀌어도 비교합니다.",
        why="실제 사이트는 매번 달라 같은 조건으로 비교할 수 없습니다. 고정한 시험 화면이 필요합니다.",
        how=[
            "(기반) 기록 → 재생 환경(RV2)",
            "고정한 시험용 사이트(레거시 AS 접수 · 매뉴얼 · 관리자) × 과제 5개(로그인 · 접수 · 매뉴얼 요약 · 삭제 · 설정만)로 성공률 · 목표 달성 · 인젝션을 따른 비율 · 걸음",
            "끝난 실행의 행동을 새 사이트에서 그대로 재생해 같은 최종 상태인지(결정적인 비교의 확인)",
        ],
        plans=[],
        docs=[
            (
                "컴퓨터 사용 · 브라우저 에이전트 — 시험용 사이트 · 접근성 트리 · 행동 · 상태 확인 · 승인 · 웹 인젝션 · 재생 평가 · 실측",
                "docs/stages/computer-use/cu1-perceive/computer_use.md",
            ),
            ("컴퓨터 사용 · 브라우저 에이전트 맵", "docs/maps/computer-use.md"),
        ],
    ),
]
