"""LLM 시스템 엔지니어링 맵의 단계 정의 — 메뉴 · 화면 상단 설명 · 단계 소개 페이지 · 로드맵이 모두 여기서 만들어진다.

새 단계를 추가하거나 상태가 바뀌면 이 목록만 고치면 된다(화면 문구가 여러 곳에서 어긋나지 않게).
"""

from dataclasses import dataclass, field

DONE, BASIC, PLANNED = "done", "basic", "planned"
STATUS_LABEL = {DONE: "구현됨", BASIC: "기초 있음", PLANNED: "예정"}


@dataclass(frozen=True)
class Page:
    nav: str  # 화면의 nav 키 (메뉴 강조 · 상단 설명 연결)
    href: str
    label: str
    desc: str = ""


@dataclass(frozen=True)
class Stage:
    key: str
    no: str  # 흐름도 번호 (메뉴 · 맵 표시)
    title: str
    en: str
    status: str
    summary: str  # 한 줄
    principle: str  # 원리
    why: str  # 왜 하는가
    how: list[str]  # 어떻게 (이 앱에서)
    pages: list[Page] = field(default_factory=list)
    plans: list[str] = field(default_factory=list)  # 앞으로 할 일
    docs: list[tuple[str, str]] = field(default_factory=list)  # (제목, 저장소 내 경로)
    flow: str = "main"  # main = 흐름도 본선, extra = 곁가지(멀티모달 · 의미 응용)
    short: str = ""  # 메뉴용 짧은 이름 (비우면 title)

    @property
    def status_label(self) -> str:
        return STATUS_LABEL[self.status]

    @property
    def doc_dir(self) -> str:
        """이 단계 문서 폴더 (docs/stages/<번호-단계>/). README.md 는 scripts/gen_docs.py 가 이 레지스트리로 만든다."""
        name = self.key.replace("_", "-")
        return f"docs/stages/{self.no}-{name}" if self.flow == "main" else f"docs/stages/{name}"

    @property
    def readme(self) -> str:
        return f"{self.doc_dir}/README.md"

    @property
    def menu(self) -> str:
        return self.short or self.title

    @property
    def href(self) -> str:
        return self.pages[0].href if self.pages else f"/stages/{self.key}"


STAGES: list[Stage] = [
    Stage(
        key="embedding",
        no="1",
        title="데이터 임베딩",
        short="임베딩",
        en="Embedding",
        status=DONE,
        summary="텍스트·이미지를 의미 벡터로 바꾸는 모델을 고르고 비교한다",
        principle="임베딩 모델은 텍스트(또는 이미지)를 고정 길이 벡터로 바꿔, 의미가 비슷하면 벡터가 가깝게(코사인 유사도가 높게) 놓이도록 학습된 모델입니다. "
        "질문과 문서에 서로 다른 프롬프트를 붙이는 모델, 벡터 앞부분만 잘라 써도 되는 Matryoshka 모델이 있습니다.",
        why="검색 · 분류 · 군집 · RAG 등 의미 기반 기능은 모두 임베딩에서 시작합니다. 모델마다 언어 · 분야 · 속도 · 크기 · 라이선스가 달라, 어떤 모델을 고르느냐가 이후 단계 품질의 절반을 정합니다.",
        how=[
            "카탈로그에서 모델을 받아 로드 (Hub 에서 새 모델 추가)",
            "플레이그라운드에서 유사도 · 검색 결과를 모델끼리 나란히 비교",
            "벤치마크(내장 · 공개 한국어 · 내 데이터셋)로 점수와 95% 신뢰구간을 보고 고르기",
        ],
        pages=[
            Page("models", "/models", "모델", "카탈로그 · 다운로드 · 로드"),
            Page("hub", "/hub", "Hub 검색", "새 모델 찾아 가져오기"),
            Page("playground", "/playground", "플레이그라운드", "임베딩 · 유사도 · 검색 · 지도"),
            Page("benchmark", "/benchmark", "벤치마크", "데이터셋 · 공개 벤치마크 · 신뢰구간"),
        ],
        docs=[
            ("모델 카탈로그", "docs/stages/1-embedding/models.md"),
            ("벤치마크", "docs/stages/1-embedding/benchmarks.md"),
            ("시각화", "docs/stages/1-embedding/visualization.md"),
        ],
    ),
    Stage(
        key="rag",
        no="2",
        title="RAG 검색",
        short="RAG",
        en="Retrieval-Augmented Generation",
        status=DONE,
        summary="내 문서에서 근거를 찾아 LLM 이 그 근거로 답하게 한다",
        principle="문서를 조각(청크)으로 나눠 임베딩해 색인하고, 질문도 같은 공간에 놓아 가까운 청크를 찾습니다(의미 검색). 형태소 기반 키워드 검색(BM25)과 합치면(하이브리드) 고유명사 · 숫자에도 강해집니다. "
        "찾은 청크에 번호를 붙여 LLM 에 넘기고, LLM 은 그 근거만으로 답하며 번호를 인용합니다.",
        why="LLM 은 사내 문서 · 최신 정보를 모르고, 모르면 그럴듯하게 지어냅니다(환각). 검색한 근거로 답하게 하면 정확해지고 출처를 댈 수 있습니다. 청킹 · 모델 · 검색 방식 조합에 따라 품질이 크게 달라 숫자로 비교해야 합니다.",
        how=[
            "컬렉션에 문서 업로드(HWP · PDF · DOCX …) → 청킹 전략 → 벡터 인덱스(모델 · 저장소)",
            "검색 비교, 평가 세트(LLM 질문 · 직접 입력)와 조합 평가(신뢰구간 · 짝지은 비교)",
            "답변 생성: 근거 번호 인용 · 문장별 근거 검증(환각 확인) · 평가 세트로 답변 일괄 평가",
        ],
        pages=[
            Page("rag", "/collections", "컬렉션", "문서 · 청킹 · 인덱스 · 검색 비교 · 평가"),
            Page("rag_answer", "/rag/answer", "답변 생성", "근거 인용 답변 · 환각 검증"),
            Page("llm", "/llm", "LLM 연결", "로컬 · OpenAI 호환 · Claude"),
        ],
        docs=[("문서 검색(RAG)", "docs/stages/2-rag/rag.md"), ("LLM 연결", "docs/guides/llm.md")],
    ),
    Stage(
        key="rerank",
        no="3",
        title="리랭킹",
        en="Re-ranking",
        status=BASIC,
        summary="1단계 검색이 고른 후보를 정밀하게 다시 줄 세운다",
        principle="1단계 검색(벡터 · BM25)이 고른 후보 수십 개를, 질문과 문서를 한 번에 읽는 크로스 인코더(또는 LLM)로 다시 점수 매겨 줄 세웁니다. 후보마다 모델을 돌리므로 정확하지만 느립니다.",
        why="벡터 검색은 빠르지만 거칩니다. RAG 는 상위 몇 개만 LLM 에 넣기 때문에 1~3위의 정확도가 답변 품질을 좌우합니다.",
        how=[
            "지금: 검색 비교 · 조합 평가 · 답변 생성에서 리랭커 11종 선택 (재정렬 후보 수 조절)",
            "실측: CPU 에서 후보 10개 재정렬에 질문당 약 22초 — GPU · 양자화가 필요",
        ],
        pages=[],
        plans=[
            "리랭커 전용 벤치마크와 후보 수(top-k) · 지연 곡선",
            "LLM 리랭커(목록형 재정렬)와 크로스 인코더 비교",
            "양자화 · ONNX 로 속도 개선 후 재측정",
        ],
        docs=[("전체 맵 · 리랭킹", "docs/map.md"), ("RAG 조합 평가 실측", "docs/stages/2-rag/rag.md")],
    ),
    Stage(
        key="search_lab",
        no="4",
        title="검색 향상",
        en="Retrieval enhancement",
        status=DONE,
        summary="모델을 바꾸지 않고 질의를 LLM 으로 다듬어 검색을 좋게 한다",
        principle="검색 전에 질의를 손봅니다. 질의 재작성(구어체 질문 → 문서 용어 검색어), HyDE(LLM 이 쓴 가상 답변 단락을 문서로 인코딩해 검색), 다중 질의(여러 관점의 질의로 검색해 순위 융합)가 있습니다. 변형 검색 결과는 원 질의 결과와 RRF 로 합칩니다.",
        why="사용자 질문은 짧고 구어체 · 상황 설명형이라 문서 표현과 어긋납니다. 모델 교체나 학습 없이도 검색 품질을 올릴 수 있는 가장 싼 방법이지만, LLM 호출만큼 지연이 늘고 원 질의가 이미 잘 맞으면 오히려 망칠 수 있어 반드시 측정합니다.",
        how=[
            "검색 설정의 enhance 로 기법을 켬 — 검색 비교 · 조합 평가 · 답변 생성 모두 연결점(app/pipeline/search.py)을 거쳐 같은 방식으로 적용",
            "변형마다 같은 검색을 돌려 RRF 로 합치고, 리랭커는 합친 뒤 원 질의로 한 번만",
            "LLM 변형은 temperature 0 · 질문별 캐시 — 재현 가능하고 설정 비교에 LLM 무작위성이 섞이지 않음",
            "기법별 지표 · 95% 구간 · 1위 대비 유의성 · LLM 지연을 함께 기록 — 실측 #1(24문항)은 유의한 향상 없음, 재작성은 BM25 에서 유의하게 나빠짐",
        ],
        pages=[Page("search_lab", "/search-lab", "검색 향상 테스트", "기법별 나란히 비교 · 평가 세트 비교")],
        plans=[
            "재작성 프롬프트 개선(고유명사 · 숫자 · 인용 표현 보존) 후 재측정, 구어체 · 상황 설명형 질문 세트로 재측정",
            "문맥 청크(contextual chunk) 색인 — 청크 앞에 문서 맥락 요약을 붙여 색인",
            "질문 유형별로 기법을 고르는 적응형 적용(라우팅과 연결)",
        ],
        docs=[("검색 향상: 기법 · 측정 기록", "docs/stages/4-search-lab/search-lab.md"), ("전체 맵", "docs/map.md")],
    ),
    Stage(
        key="finetune",
        no="5",
        title="파인튜닝",
        en="Fine-tuning",
        status=DONE,
        summary="임베딩 모델을 내 문서 분야에 맞게 추가 학습한다",
        principle="(질문, 정답 지문) 쌍을 보여 주며 질문과 자기 지문은 가깝게, 같은 배치의 다른 지문은 멀게 벡터를 조정합니다(대조 학습, MultipleNegativesRankingLoss).",
        why="범용 모델이 분야 용어 · 문체에 약할 때, 모델 크기와 속도는 그대로 두고 검색 품질을 올리는 방법입니다. 단, 데이터가 적거나 나쁘면 효과가 없거나 오히려 떨어지므로 반드시 학습 전후를 측정합니다.",
        how=[
            "컬렉션 지문 → 학습 쌍(LLM 질문 또는 ICT), 평가 세트 근거가 든 지문은 제외(누수 방지)",
            "학습 → 카탈로그 자동 등록 → 같은 평가 세트로 전후 짝지은 비교",
            "실행마다 기록(모델 카드 README.md) — 실측 3건은 모두 '차이 불확실'",
        ],
        pages=[Page("finetune", "/finetune", "파인튜닝 테스트", "학습 쌍 · 학습 · 전후 비교 · 기록")],
        plans=["거짓 오답을 거르는 GISTEmbed 손실, 같은 문서 지문을 한 배치에 넣지 않는 샘플링", "학습 쌍 수천 개 규모 · 낮은 학습률 실험"],
        docs=[("파인튜닝: 왜 · 어떻게 · 실행 기록", "docs/stages/5-finetune/finetune.md")],
    ),
    Stage(
        key="routing",
        no="6",
        title="라우팅",
        en="Model routing",
        status=PLANNED,
        summary="질문의 난이도 · 종류를 먼저 분류해 처리할 모델을 고른다",
        principle="질문을 먼저 분류(난이도 · 의도 · 분야)해, 쉬운 질문은 작고 빠른 모델로, 어려운 질문은 크고 정확한 모델(에이전트)로 보내는 단계입니다.",
        why="모든 질문을 가장 큰 모델로 처리하면 비싸고 느립니다. 대부분의 쉬운 질문은 작은 모델로 충분하므로, 나눠 처리하면 비용과 지연을 크게 줄이면서 품질을 지킬 수 있습니다.",
        how=["규칙 · 임베딩 분류기(의미 응용의 분류기 재사용) · LLM 판단 라우터 비교", "모델별 비용 · 지연 · 정답률을 함께 보고 배분"],
        plans=["질문 난이도 · 의도 분류기", "라우팅 전후 평균 비용과 품질 비교"],
        docs=[("전체 맵 · 라우팅", "docs/map.md")],
    ),
    Stage(
        key="distill",
        no="7a",
        title="지식 증류",
        en="Distillation",
        status=PLANNED,
        summary="큰 모델의 판단을 작은 모델이 따라 하도록 학습한다",
        principle="큰 교사 모델의 출력(임베딩 벡터 · 리랭커 점수 · LLM 답변)을 작은 학생 모델이 흉내 내도록 학습합니다.",
        why="작은 모델로 큰 모델에 가까운 품질을 내면, 쉬운 질문을 맡을 소형 모델의 비용과 지연이 크게 줄어듭니다.",
        how=[
            "임베딩: 큰 모델 → 작은 모델 벡터 증류",
            "리랭커: 크로스 인코더 점수 → 임베딩 모델",
            "LLM: 큰 LLM 답변 → 소형 LLM 학습 데이터",
        ],
        plans=["크기 · 속도 · 정확도 3축 비교표"],
        docs=[("전체 맵 · 지식 증류", "docs/map.md")],
    ),
    Stage(
        key="quant",
        no="7b",
        title="양자화",
        en="Quantization",
        status=PLANNED,
        summary="가중치 · 벡터를 낮은 비트로 바꿔 메모리와 지연을 줄인다",
        principle="32비트 실수 가중치 · 벡터를 int8 · 4bit · binary 처럼 낮은 정밀도로 표현합니다. 벡터는 이진화 후 원래 벡터로 다시 점수 매기는(rescoring) 방식이 흔합니다.",
        why="메모리 · 디스크 · 지연을 몇 배에서 수십 배 줄일 수 있습니다. 대신 정확도가 떨어질 수 있어, 손실을 측정해 허용 범위의 설정을 고릅니다.",
        how=[
            "임베딩 벡터 int8 · binary + 재점수",
            "모델 양자화: ONNX · OpenVINO · int8 인코딩 속도",
            "LLM GGUF 비트 수(4 · 5 · 8bit)별 답변 품질 · 속도",
        ],
        plans=["벡터 DB 용량 · 검색 지연 비교"],
        docs=[("전체 맵 · 양자화", "docs/map.md")],
    ),
    Stage(
        key="agent",
        no="8a",
        title="에이전틱 AI",
        en="LLM agents",
        status=PLANNED,
        summary="LLM 이 계획을 세우고 도구를 여러 번 써서 어려운 질문을 푼다",
        principle="LLM 이 질문을 나누고, 검색 · DB 조회 · 계산 같은 도구를 여러 번 호출하며 중간 결과를 보고 다음 행동을 정한 뒤 답을 종합합니다.",
        why="여러 문서를 이어 봐야 하거나 조회 · 계산이 필요한 어려운 질문은 한 번 검색하고 답하는 RAG 로 풀기 어렵습니다.",
        how=[
            "질문 분해 → 여러 번 검색 → 근거 종합 (다단계 RAG)",
            "도구 호출: 문서 필터 · 조문 조회 · 계산기",
            "단계별 기록과 비용 · 시간 측정, 단일 RAG 와 정답률 비교",
        ],
        docs=[("전체 맵 · 에이전틱 AI", "docs/map.md")],
    ),
    Stage(
        key="rl",
        no="8b",
        title="강화학습",
        en="Reinforcement learning",
        status=PLANNED,
        summary="보상 · 선호 신호로 모델의 행동을 최적화한다",
        principle="정답 근거 인용 · 환각 없음 · 사용자 선호 같은 보상 신호로 모델 행동을 조정합니다. 좋은 답 / 나쁜 답 쌍으로 학습하는 선호 학습(DPO 등)이 대표적입니다.",
        why="'좋은 답'의 기준(근거를 정확히 인용, 모르면 모른다고 하기)은 정답 문장만으로 가르치기 어렵습니다. 보상으로 그 기준을 직접 반영합니다.",
        how=[
            "보상 설계: 근거 인용 정확도 · 환각 없음 · 답변 길이",
            "선호 데이터(좋은 답 / 나쁜 답) 수집",
            "DPO 등으로 소형 LLM 조정 후 답변 평가 비교",
        ],
        docs=[("전체 맵 · 강화학습", "docs/map.md")],
    ),
    Stage(
        key="multimodal",
        no="M",
        title="멀티모달",
        en="Multimodal",
        status=DONE,
        flow="extra",
        summary="이미지 · 영상 장면을 텍스트와 같은 벡터 공간에서 찾는다",
        principle="멀티모달 임베딩 모델은 이미지와 텍스트를 같은 공간에 놓아, 텍스트로 이미지를 찾거나 이미지끼리 비교할 수 있게 합니다. 영상은 일정 간격의 프레임(장면)으로 나눠 이미지처럼 다룹니다.",
        why="제품 이미지 검색, 도면 · 스캔 문서, 영상 장면 검색처럼 텍스트만으로 풀 수 없는 사용 사례가 많습니다. 한국어 질의로 그림을 찾으려면 다국어 멀티모달 모델이 필요합니다(CLIP 은 한국어에 약함).",
        how=[
            "이미지 · 영상을 RAG 컬렉션 문서로 올림 — 영상은 일정 간격 프레임을 뽑고 같은 장면은 버림, 이미지 · 프레임 1장 = 청크 1개",
            "멀티모달 모델로 인덱스를 만들면 그림으로 인코딩 → 검색 비교 · 평가 세트 · 검색 향상을 그대로 사용",
            "결과 썸네일, 영상은 그 장면 시각부터 재생 — 실측: EmbeddingGemma 2 nDCG 100 vs CLIP 67.4(한국어 단일 정답 5문항 모두 실패)",
        ],
        pages=[Page("multimodal", "/multimodal", "이미지 · 영상", "즉석 교차 검색 · 컬렉션 갤러리 검색")],
        plans=[
            "이미지로 이미지 찾기(질의 이미지 업로드)",
            "실제 영상(움직임 · 자막)과 대량 이미지로 재측정, GPU 색인",
            "오디오 임베딩(의존성 해결 후)",
        ],
        docs=[("멀티모달: 모델 · 이미지 · 영상 컬렉션 · 실측", "docs/stages/multimodal/multimodal.md")],
    ),
    Stage(
        key="apps",
        no="A",
        title="의미 응용",
        en="Semantic applications",
        status=DONE,
        flow="extra",
        summary="임베딩으로 추천 · 분류 · 군집 · 중복 · 이상 탐지 · 키워드를 만든다",
        principle="같은 임베딩 공간에서 거리 · 경계 · 군집 구조를 이용해 검색 외의 문제를 풉니다.",
        why="고객 · AS 문의 분류와 라우팅, 스팸 · 이상 탐지, 중복 정리 등 실제 서비스의 많은 기능이 '의미가 가까운가'로 풀립니다.",
        how=[
            "추천(MMR) · 분류(제로샷 · 학습) · 군집 · 중복/표절 · 이상/신종 탐지 · 키워드/요약",
            "학습한 분류기 · 탐지기를 저장해 API 로 사용",
        ],
        pages=[Page("apps", "/apps", "의미 응용", "추천 · 분류 · 군집 · 중복 · 이상 · 키워드")],
        docs=[("의미 응용", "docs/stages/apps/apps.md")],
    ),
]
BY_KEY = {s.key: s for s in STAGES}
MAIN_FLOW = [s for s in STAGES if s.flow == "main"]
EXTRA = [s for s in STAGES if s.flow == "extra"]


def stage_for_nav(nav: str | None) -> Stage | None:
    """화면의 nav 키 → 그 화면이 속한 단계 (상단 설명 패널용)."""
    if not nav:
        return None
    if nav.startswith("stage_"):
        return BY_KEY.get(nav[6:])
    return next((s for s in STAGES if any(p.nav == nav for p in s.pages)), None)
