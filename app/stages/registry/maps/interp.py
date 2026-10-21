"""해석 가능성 · 모델 내부 맵 — 맵 정의와 단계. 화면 · 메뉴 · 문서가 모두 여기서 나온다(scripts/gen_docs.py)."""

from app.stages.registry.model import DONE, Map, Page, Stage

MAP = Map('interp', '해석 가능성 · 모델 내부 맵', '/maps/interp', 'docs/maps/interp.md',
        summary='임베딩 공간 분석 → 근거 기여 → 탐침 → 희소 특징 → 조종 · 편집 → 내부 신호 환각 탐지 — 모델이 왜 그렇게 답했는지 안을 보는 흐름',
        diagram='[임베딩 공간 분석] → [근거 기여]\n                    ↓\n[탐침] → [희소 특징]\n                    ↓\n[조종 · 편집] → [내부 신호 환각 탐지]',
        lead="근거 일치 검증은 답을 '밖'에서 보는 방법입니다. 작은 공개 모델(Qwen3 0.6B · 임베딩 모델)은 내부를 직접 볼 수 있어, 어느 근거 문장이 답에 기여했는지, 모델이 '모른다'를 안에서 알고 있는지, 특정 방향으로 출력을 조종할 수 있는지를 잴 수 있습니다. 규제 대응의 설명 가능성(RC4)을 모델 안쪽에서 보완합니다.",
        groups=(('공간 · 기여', ('ip_space', 'ip_attribution')), ('안을 읽기', ('ip_probe', 'ip_sae')), ('바꾸고 잡기', ('ip_steer', 'ip_hallu'))),
        principles=('밖의 검증과 비교한다 — 근거 일치 검증 실측이 기준', '작은 공개 모델로 — 안을 볼 수 있는 모델에서 재고 큰 모델은 밖에서', '설명은 재현돼야 한다 — 근거를 지웠을 때 답이 바뀌는지로 확인', '조종은 부작용을 잰다 — 같은 평가 세트 · 레드팀'),
        example="법률 답 '제23조에 따라…' → 근거 문장을 하나씩 지워 기여 확인(지우면 답이 바뀌는 문장만 진짜 근거) → 은닉 상태 탐침으로 '근거에 답 없음'을 미리 감지 → 거절 방향 조종의 부작용을 레드팀으로 → 토큰 엔트로피 환각 탐지와 근거 일치 검증의 정확도 비교.")  # fmt: skip

STAGES: list[Stage] = [
    Stage(
        key="ip_space",
        pages=[
            Page(
                "ip_space",
                "/interp/space",
                "임베딩 공간 · 희소 특징",
                "이방성 · 유효 차원 · 문서 군집 · 한-영 정렬, SAE 특징",
                "interp/space.html",
            )
        ],
        no="IP1",
        title="임베딩 공간 분석",
        short="임베딩 공간",
        en="Embedding space analysis",
        status=DONE,
        flow="interp",
        map="interp",
        builds_on=["embedding"],
        summary="차원 축소 · 군집 · 이방성 · 언어 간 정렬로 임베딩 공간을 본다",
        principle="임베딩 공간 분석은 벡터들이 어떻게 퍼져 있는지(한쪽으로 몰림 · 군집 · 한국어-영어 정렬)를 보는 것입니다. 검색 품질 차이의 원인을 공간에서 찾습니다.",
        why="같은 점수의 두 모델도 공간 모양이 달라 양자화 · 차원 줄이기에서 다르게 무너집니다.",
        how=[
            "(기반) 임베딩 투영 · 벤치마크(1)",
            "같은 청크로 모델마다 이방성(아무 두 글의 평균 코사인) · 유효 차원(특이값 참여 비율) · 상위 10 · 50 주성분 설명력 · 문서 군집(같은 문서 − 다른 문서 코사인)",
            "한국어-영어 번역 쌍 12개로 언어 간 정렬(가장 가까운 영어가 번역인 비율 · 번역 쌍 − 아무 쌍 코사인)",
        ],
        plans=[],
        docs=[
            (
                "해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측",
                "docs/stages/interp/ip1-space/interp.md",
            ),
            ("해석 가능성 · 모델 내부 맵", "docs/maps/interp.md"),
        ],
    ),
    Stage(
        key="ip_attribution",
        pages=[
            Page(
                "ip_attribution", "/interp/attribution", "근거 기여", "근거 지우기 · 어텐션 vs 인용 · 정답 근거", "interp/attribution.html"
            )
        ],
        no="IP2",
        title="근거 기여",
        short="근거 기여",
        en="Attribution",
        status=DONE,
        flow="interp",
        map="interp",
        builds_on=["rc_explain"],
        summary="어텐션 · 그래디언트 · 근거 지우기로 어느 문장이 답에 기여했는지 잰다",
        principle="근거 기여는 답의 각 부분이 맥락의 어느 문장에서 왔는지를 모델 안에서 재는 것입니다. 근거를 하나씩 지워 답이 바뀌는지가 가장 확실한 확인입니다.",
        why="답이 인용한 근거와 실제로 기댄 근거가 다를 수 있습니다. 설명 가능성은 인용이 아니라 기여로 확인해야 합니다.",
        how=[
            "(기반) 설명 가능성(RC4)",
            "작은 공개 LLM 이 쓴 답에 대해 근거를 하나씩 지웠을 때 같은 답의 로그확률 하락(지우기 기여) · 답 토큰이 근거마다 준 어텐션(마지막 4층)",
            "기여 1위가 정답 근거 · 답이 인용한 번호와 같은지, 어텐션과 지우기 기여가 같은 근거를 가리키는지",
        ],
        plans=[],
        docs=[
            (
                "해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측",
                "docs/stages/interp/ip1-space/interp.md",
            ),
            ("해석 가능성 · 모델 내부 맵", "docs/maps/interp.md"),
        ],
    ),
    Stage(
        key="ip_probe",
        pages=[
            Page(
                "ip_inside",
                "/interp/inside",
                "탐침 · 조종 · 내부 환각 탐지",
                "근거 있음 / 뺌 층별 탐침 · AUROC · 조종",
                "interp/inside.html",
            )
        ],
        no="IP3",
        title="탐침",
        short="탐침",
        en="Probing",
        status=DONE,
        flow="interp",
        map="interp",
        builds_on=["apps"],
        summary="은닉 상태로 '근거에 답이 있나' · 주제 · 언어를 선형 분류한다",
        principle="탐침은 모델의 중간 은닉 상태에 작은 선형 분류기를 붙여, 모델이 안에서 무엇을 알고 있는지(답이 근거에 있는지 등)를 읽는 것입니다.",
        why="모델이 '모른다'를 안에서 알면서도 답을 지어낸다면, 출력 전에 그 신호로 막을 수 있습니다.",
        how=[
            "(기반) 의미 응용 분류기(A)",
            "같은 질문을 정답 근거 있음 / 뺌 두 벌로, 층마다 프롬프트 마지막 토큰 은닉 상태를 선형 분류(교차 검증) — 모델이 어느 층에서 '답이 근거에 없다'를 아는가",
            "은닉 상태를 파일로 남겨 조종 방향 · 탐침 점수가 같은 자료를 씀",
        ],
        plans=[],
        docs=[
            (
                "해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측",
                "docs/stages/interp/ip1-space/interp.md",
            ),
            ("해석 가능성 · 모델 내부 맵", "docs/maps/interp.md"),
        ],
    ),
    Stage(
        key="ip_sae",
        pages=[Page("ip_sae", "/interp/space#sae", "희소 특징", "SAE 학습 · 특징별 켜지는 글 조각")],
        no="IP4",
        title="희소 특징",
        short="희소 특징",
        en="Sparse autoencoders",
        status=DONE,
        flow="interp",
        map="interp",
        builds_on=["pt_adapter"],
        summary="은닉 상태를 사람이 읽을 수 있는 희소 특징으로 나눈다",
        principle="희소 오토인코더(SAE)는 은닉 상태를 수천 개의 희소한 특징으로 다시 표현해, 특징마다 어떤 글에서 켜지는지로 뜻을 붙이는 방법입니다.",
        why="은닉 상태의 차원 하나는 뜻이 섞여 있습니다. 희소 특징은 '법 조문' · '거절' 같은 개념 단위로 볼 수 있게 합니다.",
        how=[
            "(기반) 작은 공개 모델 · 학습기(P5)",
            "한 층의 토큰 은닉 상태(표준화)로 희소 오토인코더(특징 배수 · L1) 학습, 특징 방향 길이 1 로 고정",
            "설명한 분산 · 평균 켜진 특징 수(L0) · 안 켜진 특징 비율, 자주 · 세게 켜지는 특징의 글 조각",
        ],
        plans=[],
        docs=[
            (
                "해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측",
                "docs/stages/interp/ip1-space/interp.md",
            ),
            ("해석 가능성 · 모델 내부 맵", "docs/maps/interp.md"),
        ],
    ),
    Stage(
        key="ip_steer",
        pages=[Page("ip_steer", "/interp/inside#steer", "조종", "근거 뺌 − 있음 방향 · 세기별 거절률")],
        no="IP5",
        title="조종 · 편집",
        short="조종 · 편집",
        en="Steering & editing",
        status=DONE,
        flow="interp",
        map="interp",
        builds_on=["pt_adapter"],
        summary="특징 방향을 더해 말투 · 거절을 조종하고 부작용을 잰다",
        principle="조종은 생성 중 은닉 상태에 특정 방향(말투 · 거절 · 주제)을 더해 출력을 바꾸는 것이고, 편집은 특정 사실의 저장을 바꾸는 것입니다. 학습 없이 바꿀 수 있지만 부작용이 있습니다.",
        why="후학습보다 싸게 행동을 바꿀 수 있는지, 그때 다른 능력 · 안전이 떨어지지 않는지를 같은 평가로 확인해야 합니다.",
        how=[
            "(기반) 어댑터 · 병합(P5)",
            "탐침이 가장 잘 맞힌 층의 '근거 뺌 평균 − 근거 있음 평균' 방향을 그 층 블록 출력에 더해 생성",
            "세기별 근거 뺌 거절률(오르면 좋음) · 근거 있음 거절률(오르면 부작용) · 근거 있음 답의 근거율",
        ],
        plans=[],
        docs=[
            (
                "해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측",
                "docs/stages/interp/ip1-space/interp.md",
            ),
            ("해석 가능성 · 모델 내부 맵", "docs/maps/interp.md"),
        ],
    ),
    Stage(
        key="ip_hallu",
        pages=[Page("ip_hallu", "/interp/inside#probe", "내부 신호 환각 탐지", "엔트로피 · 최소 확률 · 탐침 vs 글자 근거율")],
        no="IP6",
        title="내부 신호 환각 탐지",
        short="내부 환각 탐지",
        en="Internal uncertainty",
        status=DONE,
        flow="interp",
        map="interp",
        builds_on=["as_verify"],
        summary="토큰 확률 · 엔트로피 · 탐침으로 근거 없는 답을 잡고 근거 일치 검증과 비교한다",
        principle="내부 신호 환각 탐지는 생성 중 토큰 확률 · 엔트로피 · 탐침 점수로 '모르면서 답하는' 부분을 찾는 것입니다.",
        why="밖의 근거 일치 검증은 답이 끝난 뒤에야 판정합니다. 내부 신호가 같은 정확도로 더 일찍 잡는지, 둘을 합치면 나은지 잽니다.",
        how=[
            "(기반) 근거 일치 검증(AS6)",
            "거절하지 않은 답 중 근거 없이 답한 것(근거 뺌 쪽)을 가려내는 AUROC — 내부 신호(평균 엔트로피 · 최소 확률 · 탐침 점수, 교차 적합)와 밖의 검증(글자 근거율)",
            "내부 신호는 생성 중에, 밖의 검증은 답이 끝난 뒤에 얻는다 — 같은 자료로 비교",
        ],
        plans=[],
        docs=[
            (
                "해석 가능성 — 임베딩 공간 · 근거 기여 · 탐침 · 희소 특징 · 조종 · 내부 신호 환각 탐지 · 실측",
                "docs/stages/interp/ip1-space/interp.md",
            ),
            ("해석 가능성 · 모델 내부 맵", "docs/maps/interp.md"),
        ],
    ),
]
