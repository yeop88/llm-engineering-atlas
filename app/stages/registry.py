"""맵과 단계 정의 — 메뉴 · 화면 상단 설명 · 단계 소개 페이지 · 맵 화면 · 문서가 모두 여기서 만들어진다.

맵은 여러 개다: ① LLM 시스템 엔지니어링 맵(임베딩 → RAG → … → 에이전트) ② 지식 그래프 · GraphRAG 맵(온톨로지 → 그래프 DB → GraphRAG)
③ 멀티에이전트 · 멀티모달 맵(오케스트레이터와 전문가 에이전트, 텍스트 밖의 입력 · 출력).
다른 맵의 단계는 builds_on 으로 LLM 맵의 어느 단계 위에 짓는지 적는다 — 이미 구현된 것과 새로 만들 것을 나눠 보이려고.
단계는 하나의 목록(STAGES)에 두고 map 으로 나눈다 — 단계 소개 페이지 · 문서 생성 · 메뉴 강조를 맵마다 따로 만들지 않으려고.
새 단계를 추가하거나 상태가 바뀌면 이 목록만 고치면 된다(화면 문구가 여러 곳에서 어긋나지 않게).
"""

from dataclasses import dataclass, field

DONE, BASIC, PLANNED = "done", "basic", "planned"
STATUS_LABEL = {DONE: "구현됨", BASIC: "기초 있음", PLANNED: "예정"}


@dataclass(frozen=True)
class Map:
    key: str
    title: str
    href: str
    doc: str  # 맵 개요 문서 (저장소 내 경로)
    summary: str
    diagram: str = ""  # 문서 색인에 넣는 글자 흐름도


MAPS: list[Map] = [
    Map("llm", "LLM 시스템 엔지니어링 맵", "/roadmap", "docs/map.md",
        "임베딩 → RAG 검색 → 리랭킹 → 라우팅 → 소형/대형 모델 · 에이전트 — 문서 지식을 싸고 빠르고 정확하게 서비스하는 흐름",
        "[데이터 임베딩] → [RAG 검색] → [리랭킹 (정밀 필터링)]\n"
        "                                        ↓\n"
        "[라우팅 (난이도 분류)] → 쉬운 질문:  [지식 증류 · 양자화된 소형 모델]\n"
        "                       → 어려운 질문: [파인튜닝 · 강화학습된 에이전트 LLM]"),
    Map("kg", "지식 그래프 · GraphRAG 맵", "/maps/knowledge-graph", "docs/kg-map.md",
        "온톨로지 설계 → 추출 · 융합 → 그래프 DB → GraphRAG — 개념과 관계를 구조로 저장해 다단계 · 집계 · 전체 요약 질문에 답하는 흐름",
        "[요구사항 정의] → [온톨로지 설계] → [데이터 추출 (ETL · LLM)] → [지식 융합 · 정제]\n"
        "                                        ↓\n"
        "                              [그래프 DB (Neo4j)]\n"
        "                                        ↓\n"
        "  GraphRAG: [Text2Cypher] · [그래프 하이브리드 검색] · [글로벌 커뮤니티 요약]"),
    Map("agents", "멀티에이전트 · 멀티모달 맵", "/maps/multi-agent", "docs/agents-map.md",
        "멀티모달 입력 · 검색 → 오케스트레이터가 전문가 에이전트(검색 · 분석 · 작성 · 검증)에게 분배 → 교차 검증 → 텍스트 · 차트 · 음성 출력",
        "[멀티모달 입력 (텍스트 · 이미지 · 음성 · 문서)] → [멀티모달 임베딩]\n"
        "                                        ↓\n"
        "                     [오케스트레이터 에이전트 (작업 분해 · 분배)]\n"
        "          ↓                             ↓                              ↓\n"
        "  [검색 전문가 (멀티모달 RAG)]   [분석 · 코딩 (표 · 코드 · 차트)]   [보고서 작성 (sLLM / LLM)]\n"
        "                                        ↓\n"
        "                     [품질 검증 (Critic) · 교차 검증]\n"
        "                                        ↓\n"
        "                [멀티모달 출력 (텍스트 + 차트 + 음성)]"),
]  # fmt: skip
MAP_BY_KEY = {m.key: m for m in MAPS}


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
    flow: str = "main"  # main = 흐름도 본선, extra = 곁가지(멀티모달 · 의미 응용), kg = 지식 그래프 맵
    short: str = ""  # 메뉴용 짧은 이름 (비우면 title)
    map: str = "llm"  # 속한 맵 (MAPS)
    builds_on: list[str] = field(default_factory=list)  # 이 단계가 위에 짓는 다른 단계(주로 LLM 맵의 구현된 단계) 키

    @property
    def status_label(self) -> str:
        return STATUS_LABEL[self.status]

    @property
    def doc_dir(self) -> str:
        """이 단계 문서 폴더 (docs/stages/<번호-단계>/). README.md 는 scripts/gen_docs.py 가 이 레지스트리로 만든다."""
        name = self.key.replace("_", "-")
        if self.map != "llm":
            return f"docs/stages/{self.map}/{self.no.lower()}-{name.removeprefix(self.map + '-')}"
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

    @property
    def map_info(self) -> Map:
        return MAP_BY_KEY[self.map]


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
            "컬렉션에 문서 업로드(HWP · PDF · DOCX …) 또는 공개 자료 가져오기(법령 · 판례) → 청킹 전략 → 벡터 인덱스(모델 · 저장소)",
            "검색 비교, 평가 세트(LLM 질문 7유형 — 조건 · 긴 상황 · 여러 문서 · 답 없음 포함, 직접 입력)와 조합 평가(신뢰구간 · 짝지은 비교)",
            "답변 생성: 질문에 대한 답 + 관련된 부가 설명만, 근거 번호 인용 · 문장별 근거 일치와 질문 관련성 검증 · 평가 세트로 답변 일괄 평가",
        ],
        pages=[
            Page("rag", "/collections", "컬렉션", "문서 · 청킹 · 인덱스 · 검색 비교 · 평가"),
            Page("rag_answer", "/rag/answer", "답변 생성", "근거 인용 답변 · 환각 검증"),
            Page("rag_verify", "/rag/verify", "검증 보정", "사람 판정(근거 일치 · 질문 관련성)으로 검증 방식과 기준 고르기"),
            Page("llm", "/llm", "LLM 연결", "로컬 · OpenAI 호환 · Claude"),
        ],
        plans=[
            "비슷한 문서가 많은 자료(판례)에서 답 없는 질문 거절 개선 — 법률 재측정에서 13개 중 1개만 거절",
            "여러 문서 질문을 늘린 평가 세트(관련 지문 쌍이 적어 9문항뿐)",
        ],  # fmt: skip
        docs=[("문서 검색(RAG)", "docs/stages/2-rag/rag.md"), ("LLM 연결", "docs/guides/llm.md")],
    ),
    Stage(
        key="rerank",
        no="3",
        title="리랭킹",
        en="Re-ranking",
        status=DONE,
        summary="1단계 검색이 고른 후보를 정밀하게 다시 줄 세운다",
        principle="1단계 검색(벡터 · BM25)이 고른 후보 수십 개를, 질문과 문서를 한 번에 읽는 크로스 인코더 또는 LLM 으로 다시 점수 매겨 줄 세웁니다. 후보마다 모델을 돌리므로 정확하지만 느립니다.",
        why="벡터 검색은 빠르지만 거칩니다. RAG 는 상위 몇 개만 LLM 에 넣기 때문에 1~3위의 정확도가 답변 품질을 좌우합니다. 다만 리랭커가 1단계의 정답을 끌어내리는 경우도 있어(실측) 반드시 재고 씁니다.",
        how=[
            "크로스 인코더 리랭커(11종) · LLM 목록형 리랭커(후보를 한 번에 보여 주고 순서를 받음 — 호출 1번)",
            "리랭크 융합: 리랭커 순위와 1단계 순위를 RRF 로 합쳐 한쪽의 실수를 다른 쪽이 메움",
            "평가: 리랭커 × 후보 수 × 융합의 품질-지연 — 크로스 인코더 점수는 가장 큰 후보 수에서 한 번만 매기고 잘라 계산",
        ],
        pages=[Page("rerank", "/rerank", "리랭킹 테스트", "리랭커 · 후보 수 · 융합 · LLM 리랭커 비교")],
        plans=["리랭커 int8 · ONNX 로 CPU 지연 줄이기(7b 와 연결)", "질문 유형별로 리랭킹을 켜고 끄는 라우팅"],
        docs=[("리랭킹: 방법 · 실측", "docs/stages/3-rerank/rerank.md"), ("전체 맵", "docs/map.md")],
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
        status=DONE,
        summary="질문의 난이도를 먼저 판단해 쉬운 질문은 싼 경로, 어려운 질문은 비싼 경로로 보낸다",
        principle="질문을 먼저 분류해, 쉬운 질문은 작고 빠른 모델 · 짧은 경로로, 어려운 질문은 크고 정확한 모델(에이전트) · 전체 경로로 보냅니다. 판단 방법은 규칙(질문 형태), 검색 확신도(1·2위 점수 차), LLM 판단을 비교합니다.",
        why="모든 질문을 가장 비싼 경로로 처리하면 느리고 비쌉니다. 연결 실측에서 지연의 대부분이 답변 LLM 과 CPU 리랭커였으므로, 리랭커 · 큰 모델이 필요 없는 질문을 가려내면 품질을 지키며 비용을 줄일 수 있습니다.",
        how=[
            "쉬운 경로(1 → 2 → 답변)와 전체 경로(4 → 1 → 2 → 3 → 답변)를 정하고 라우터가 질문마다 고름 — 경로마다 답변 모델 지정 가능(7 소형 모델 자리)",
            "평가: 질문마다 두 경로를 한 번씩 실행해 두고 라우터별 결과를 그 기록으로 계산 — 항상 쉬움 · 항상 전체 · 오라클(상한)과 비교, 확신도 기준값 곡선",
            "연결 실행(맵)에서도 라우팅을 켤 수 있음 — 확신도 라우터는 먼저 한 검색을 쉬운 경로에서 재사용",
            "학습 라우터: 평가 기록의 오라클 판단을 라벨로 질문 임베딩 + 확신도 + 질문 형태를 로지스틱 회귀로 학습, 교차검증으로 같은 기록의 다른 라우터와 비교",
        ],
        pages=[Page("routing", "/routing", "라우팅 테스트", "라우터 판단 · 평가 세트 비용-품질 비교")],
        plans=[
            "학습 라우터를 질문 수백 개 기록으로 다시 학습 · 측정 (법률 40문항에서 '어려움' 라벨 5개뿐)",
            "규칙 라우터 글자 수 기준을 자료의 질문 길이 분포에 맞추기 (법률 질문에선 92.5% 를 어려움으로 보냄)",
            "빠른 경로 모델: E2B 는 품질 −13 유의라 부적합 — 증류한 소형 모델로 다시",
        ],
        docs=[("라우팅: 라우터 · 평가 방법 · 실측", "docs/stages/6-routing/routing.md"), ("전체 맵", "docs/map.md")],
    ),
    Stage(
        key="distill",
        no="7a",
        title="지식 증류",
        en="Distillation",
        status=DONE,
        summary="큰 모델의 판단을 작은 모델이 따라 하도록 학습한다",
        principle="큰 교사 모델의 출력(임베딩 점수 · 리랭커 점수 · LLM 답변)을 작은 학생 모델이 흉내 내도록 학습합니다. 임베딩은 교사가 매긴 '정답 − 오답' 점수 차를 학생이 배우는 MarginMSE 를 씁니다 — 점수 차이를 배우므로 교사 · 학생의 차원이 달라도 되고 교사가 리랭커여도 됩니다.",
        why="작은 모델로 큰 모델에 가까운 품질을 내면, 쉬운 질문을 맡을 소형 모델(라우팅의 빠른 경로)의 비용과 지연이 크게 줄어듭니다.",
        how=[
            "임베딩 증류: 학습 질문(LLM · ICT) → 교사가 어려운 오답 고르기 · 점수 차 → 학생 학습(MarginMSE) → 카탈로그 등록 → 교사 · 학생 전 · 후 비교와 격차 회복률 · 인코딩 속도",
            "LLM 증류 데이터: 컬렉션 지문으로 새 질문 → 교사 LLM 이 서비스와 같은 형식으로 답 → 검증 통과한 답만 대화형 JSONL (학습은 GPU 환경)",
            "평가 세트 근거가 든 지문은 학습에서 제외(누수 방지), 실행 기록은 파인튜닝과 함께 관리",
        ],
        pages=[Page("distill", "/distill", "지식 증류 테스트", "임베딩 증류 · LLM 증류 데이터")],
        plans=["증류한 소형 LLM 을 라우팅의 빠른 경로 모델로 연결", "리랭커 → 임베딩 증류 실측"],
        docs=[("지식 증류: 방법 · 실측", "docs/stages/7a-distill/distill.md"), ("전체 맵", "docs/map.md")],
    ),
    Stage(
        key="quant",
        no="7b",
        title="양자화",
        en="Quantization",
        status=DONE,
        summary="가중치 · 벡터를 낮은 비트로 바꿔 메모리와 지연을 줄이고, 정확도 손실을 잰다",
        principle="32비트 실수 가중치 · 벡터를 int8 · 4bit · binary 처럼 낮은 정밀도로 표현합니다. 벡터는 이진화해 해밍 거리로 후보를 넉넉히 뽑은 뒤 더 정밀한 값으로 다시 점수 매기는(재점수) 방식이 흔합니다.",
        why="메모리 · 디스크 · 지연을 몇 배에서 수십 배 줄일 수 있습니다. 대신 정확도가 떨어질 수 있어, 손실을 측정해 허용 범위의 설정을 고릅니다. 라우팅의 빠른 경로에 쓸 작고 빠른 모델을 고르는 근거가 됩니다.",
        how=[
            "2026-10 기준 기술 카탈로그(원리 · 장단점 · 언제)에서 골라 실행 — 벡터(float16 · int8 · int4 · binary · 재점수 · PQ), 차원(MRL), 모델 가중치(bf16 · int8 동적), LLM(GGUF legacy · K · I · 동적 혼합 · QAT · KV 캐시)",
            "여러 양자화를 동시에: 가중치 × 차원 × 벡터 정밀도의 모든 조합을 공개 벤치마크로 채점, 기준과 짝지은 비교 · 기준 상위 10 유지율 · 메모리, 파레토 최적 표시",
            "LLM: GGUF 가중치 × KV 캐시 양자화를 함께 적용한 서버 명령을 만들고, 같은 질문 · 같은 근거로 근거 인용 · 속도 비교 (모델별 서버 주소 OPENAI_MODEL_URLS)",
        ],
        pages=[Page("quant", "/quant", "양자화 테스트", "벡터 정밀도 · LLM 비트 수 비교")],
        plans=[
            "ONNX · OpenVINO int8 실행(추가 의존성)",
            "리랭커 int8(CPU 리랭킹 지연 22초 줄이기)",
            "벡터 DB 내장 양자화(Qdrant scalar · binary · product, pgvector halfvec · bit)로 실제 검색 지연",
            "RaBitQ 실행",
        ],
        docs=[("양자화: 방법 · 실측", "docs/stages/7b-quant/quant.md"), ("전체 맵", "docs/map.md")],
    ),
    Stage(
        key="agent",
        no="8a",
        title="에이전틱 AI",
        en="LLM agents",
        status=DONE,
        summary="LLM 이 도구를 여러 번 써서 어려운 질문을 푼다",
        principle="LLM 이 생각 → 도구 호출 → 관찰을 반복합니다(ReAct). 도구는 검색(다른 표현 · 하위 질문), 읽기(찾은 지문의 앞뒤), 계산이고, 모은 지문을 번호로 인용해 답합니다.",
        why="여러 문서를 이어 봐야 하거나 청크 경계에서 잘린 표 · 조문, 계산이 필요한 어려운 질문은 한 번 검색하고 답하는 RAG 로 풀기 어렵습니다.",
        how=[
            "JSON 한 객체로 행동 선택(작은 로컬 LLM 의 함수 호출 지원이 고르지 않아), 형식 오류 · 단계 상한이면 모은 근거로 답함",
            "단계별 생각 · 행동 · 관찰 · 시간 기록(스트리밍), 답은 RAG 와 같은 문장별 근거 검증",
            "연결 실행 · 라우팅의 어려운 경로에 '에이전트로 답하기'를 켜서 일반 RAG 와 같은 질문으로 비교",
            "법률 자료용 번호 조회 도구(조문 · 사건번호로 바로 찾기)와 답변의 번호 검사(근거에 있음 · 자료에만 있음 · 자료에 없음)",
        ],
        pages=[Page("agent", "/agent", "에이전트 테스트", "도구를 여러 번 쓰는 다단계 RAG")],
        plans=[
            "질문 분해(병렬 하위 검색)",
            "날짜 · 기간 계산 같은 구조화 도구",
            "판례 질문에서 근거 밖 문장을 줄이기(문장 근거율 50% vs RAG 91%)",
            "질문에 번호가 있으면 에이전트, 없으면 RAG 로 보내는 규칙 라우팅",
        ],
        docs=[("에이전트: 방법 · 실측", "docs/stages/8a-agent/agent.md"), ("전체 맵", "docs/map.md")],
    ),
    Stage(
        key="rl",
        no="8b",
        title="강화학습",
        en="Reinforcement learning",
        status=DONE,
        summary="보상 · 선호 신호로 답변 행동을 좋게 만든다",
        principle="'좋은 답'의 기준(근거로 뒷받침된 문장, 정답 근거 인용, 없는 근거 인용 · 근거가 있는데 거절은 감점)을 보상 함수로 만들고, 보상으로 답을 고르거나(Best-of-N) 좋은 답 / 나쁜 답 쌍으로 모델을 조정합니다(DPO 등 선호 학습).",
        why="'근거를 정확히 인용하고 모르면 모른다고 하기'는 정답 문장만으로 가르치기 어렵습니다. 보상으로 그 기준을 직접 반영합니다.",
        how=[
            "설명 가능한 단순 합의 보상 함수 (학습된 보상 모델은 판단 근거 · 보상 해킹을 찾기 어려움)",
            "Best-of-N: 평소 답(후보 0)과 다양한 후보 중 보상 최고 — 학습 없이 효과 측정, 연결 실행 경로 옵션으로도 사용",
            "선호 쌍: 보상 차가 큰 쌍 자동 저장 + 사람이 두 답 중 고르기, DPO 형식 JSONL 내보내기 (학습은 GPU 환경)",
        ],
        pages=[Page("rl", "/rl", "강화학습 테스트", "보상 · Best-of-N · 선호 쌍 · DPO 데이터")],
        plans=["DPO 로 학습한 소형 LLM 을 연결해 전후 비교", "사람 선호와 보상의 일치율로 보상 함수 고치기"],
        docs=[("강화학습: 보상 · 방법 · 실측", "docs/stages/8b-rl/rl.md"), ("전체 맵", "docs/map.md")],
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
    # ── 지식 그래프 · GraphRAG 맵 (K1~K8) ─────────────────────────────────────
    # 구축은 탑다운(요구사항 → 온톨로지, 스키마 먼저)과 바텀업(데이터에서 추출, 데이터 먼저)을 섞는다. 첫 적용 도메인은 이미 있는
    # 법률 공개 자료(법령 6 · 판례 164): 판례마다 참조조문이 있어 '판례 -인용-> 조문' 관계를 추출 없이 바로 만들 수 있다.
    Stage(
        key="kg_requirements",
        no="K1",
        title="요구사항 정의",
        short="요구사항",
        en="Competency questions",
        status=PLANNED,
        flow="kg",
        map="kg",
        summary="지식 그래프가 답해야 할 업무 질문 10~15개로 그래프의 범위를 정한다",
        principle="역량 질문(Competency Questions)은 '이 그래프로 무엇에 답할 수 있어야 하는가'를 질문 목록으로 적은 것입니다. "
        "어떤 개념 · 관계 · 속성이 필요한지는 이 질문들에서 거꾸로 정해지고, 완성된 그래프가 질문에 실제로 답하는지가 검수 기준이 됩니다.",
        why="범위를 정하지 않고 '문서에 있는 것을 전부' 그래프로 만들면 개념이 끝없이 늘고 관계 이름이 제각각이 되어 쿼리할 수 없는 그래프가 됩니다. "
        "질문이 먼저 있어야 온톨로지를 작게 시작해 필요할 때 넓힐 수 있습니다.",
        how=[
            "(예정) 도메인별 역량 질문 목록과 기대 답(쿼리 결과)을 평가 세트처럼 저장 — 예: '근로기준법 제23조를 인용한 대법원 판례 중 해고가 무효로 판단된 사건은?'",
            "(예정) 질문마다 필요한 개념 · 관계를 표시해 온톨로지 설계(K2)의 입력으로 사용",
            "(예정) 벡터 RAG 로 답하기 어려운 질문(다단계 · 집계 · 전체 요약)을 따로 표시 — GraphRAG(K6~K8)의 효과를 잴 대상",
        ],
        plans=["법률 자료로 역량 질문 15개 작성(판례-조문 인용 · 쟁점별 집계 · 법령 간 위임 관계)", "질문 → 기대 Cypher · 기대 답 기록"],
        docs=[("지식 그래프 · GraphRAG 맵", "docs/kg-map.md")],
    ),
    Stage(
        key="ontology",
        no="K2",
        title="온톨로지 설계",
        short="온톨로지",
        en="Ontology design",
        status=PLANNED,
        flow="kg",
        map="kg",
        summary="도메인의 개념(클래스) · 속성 · 관계와 그 규칙을 기계가 읽는 스키마로 정의한다",
        principle="온톨로지는 지식 그래프의 설계도입니다. 어떤 클래스(개념)가 있고, 각 클래스가 어떤 속성(Property)과 관계(Relationship)를 갖는지, "
        "관계의 방향 · 개수 · 값의 형식 같은 규칙을 정합니다. W3C 표준으로는 데이터 모델 RDF, 개념 · 관계 정의 OWL, 검증 규칙 SHACL 이 있고, "
        "속성 그래프(Neo4j)에서는 노드 레이블 · 관계 타입 · 제약 조건으로 같은 일을 합니다.",
        why="추출(K3)과 융합(K4)이 같은 설계도를 따라야 '판례가 조문을 인용한다'는 사실이 문서마다 다른 이름의 관계로 흩어지지 않습니다. "
        "검증 규칙이 있어야 잘못 추출된 관계(조문이 판례를 인용 등)를 저장 전에 걸러 정합성을 지킬 수 있습니다.",
        how=[
            "(예정) 원칙: 명확성(개념마다 정의 한 줄) · 정합성(검증 규칙) · 확장성(나중에 개념을 더해도 기존 관계가 깨지지 않게)",
            "(예정) 법률 예시 — 클래스: 법령 · 조문 · 항 · 판례 · 쟁점 · 당사자 유형 / 관계: 판례 -인용-> 조문, 조문 -속함-> 법령, 시행령 조문 -위임 근거-> 법률 조문, 판례 -다룸-> 쟁점",
            "(예정) 설계를 YAML(또는 OWL · SHACL)로 저장하고, 추출 프롬프트 · 그래프 DB 제약 조건 · Text2Cypher 스키마 설명을 모두 여기서 만든다",
        ],
        plans=["법률 온톨로지 v1 (클래스 6 · 관계 6 안팎)", "검증 규칙(관계 방향 · 필수 속성)으로 추출 결과 거르기"],
        docs=[("지식 그래프 · GraphRAG 맵", "docs/kg-map.md")],
    ),
    Stage(
        key="kg_extract",
        builds_on=["rag"],
        no="K3",
        title="데이터 추출",
        short="추출",
        en="ETL & LLM extraction",
        status=PLANNED,
        flow="kg",
        map="kg",
        summary="정형 데이터는 스키마 매핑으로, 비정형 문서는 LLM 으로 [주어-관계-목적어] 트리플을 뽑는다",
        principle="정형 데이터(RDB · CSV)는 테이블 열을 온톨로지의 클래스 · 속성 · 관계에 대응시켜(매핑) 그대로 옮깁니다. "
        "비정형 문서(보고서 · 판결문)는 LLM 으로 개체명 인식(NER)과 관계 추출(RE)을 해 [주어-관계-목적어] 트리플을 만듭니다. 추출 결과에는 근거 문장 · 문서를 함께 남깁니다.",
        why="그래프의 품질은 추출에서 정해집니다. 정형 데이터가 있으면 추출보다 매핑이 정확하고 싸므로 먼저 쓰고, LLM 추출은 매핑으로 얻을 수 없는 관계에만 씁니다. "
        "근거를 남겨야 GraphRAG 답변이 RAG 처럼 출처를 댈 수 있습니다.",
        how=[
            "(예정) 정형: 판례 메타데이터의 참조조문 · 사건번호 · 선고일 → 판례 · 조문 노드와 '인용' 관계 (추출 없이 바로 — 이미 수집한 자료)",
            "(예정) 비정형: 판결요지 · 조문 본문에서 LLM(로컬 Gemma 4) 으로 쟁점 · 요건 · 효과 관계 추출, 온톨로지(K2)에 없는 관계 타입은 버림",
            "(예정) 추출 정확도를 사람 판정 표본으로 측정(트리플 정밀도 · 재현율) — 답변 검증 보정과 같은 방식",
        ],
        plans=["정형 매핑으로 판례-조문 그래프 먼저 (LLM 없이)", "LLM 트리플 추출 + 검증 규칙 + 사람 판정 표본"],
        docs=[("지식 그래프 · GraphRAG 맵", "docs/kg-map.md")],
    ),
    Stage(
        key="kg_fusion",
        builds_on=["rag", "apps"],
        no="K4",
        title="지식 융합 · 정제",
        short="융합 · 정제",
        en="Knowledge fusion",
        status=PLANNED,
        flow="kg",
        map="kg",
        summary="다른 이름의 같은 개체를 하나로 묶고(개체 정규화) 중복 · 충돌을 정리해 그래프를 완성한다",
        principle="여러 문서에서 나온 '미국' · 'USA' · 'United States' 처럼 같은 대상을 가리키는 개체를 하나의 노드로 묶습니다(개체 정규화 · 연결). "
        "이름 규칙 · 사전 · 임베딩 유사도 · LLM 판단을 섞어 후보를 찾고, 같은 관계의 중복과 서로 어긋나는 사실을 정리합니다.",
        why="정규화하지 않으면 같은 조문이 '근로기준법 제23조' · '근기법 23조' · '같은 법 제23조 제1항' 처럼 여러 노드로 갈라져, "
        "다단계 탐색이 중간에 끊기고 집계가 틀립니다. 그래프의 연결이 곧 답이므로 여기서의 오류가 그대로 오답이 됩니다.",
        how=[
            "(예정) 조문 번호 정규화는 이미 있는 파서(`rag/legal.py` — 시행령 · '의2' · 띄어쓰기 처리)를 그대로 사용",
            "(예정) 이름이 다른 개체는 임베딩 유사도로 후보 → 규칙 · LLM 으로 확정, 합친 기록(어느 이름을 합쳤나)을 남김",
            "(예정) 정제 결과를 역량 질문(K1)으로 점검 — 합치기 전후 답이 달라지는 질문을 확인",
        ],
        plans=["조문 · 사건번호 정규화(파서 재사용)", "개체 연결 후보의 정밀도를 사람 판정으로 측정"],
        docs=[("지식 그래프 · GraphRAG 맵", "docs/kg-map.md")],
    ),
    Stage(
        key="graph_db",
        builds_on=["rag"],
        no="K5",
        title="그래프 DB",
        short="그래프 DB",
        en="Graph database (Neo4j)",
        status=PLANNED,
        flow="kg",
        map="kg",
        summary="노드와 관계로 저장하고, JOIN 없이 이웃을 따라가는 다단계 탐색과 벡터 검색을 한 곳에서 한다",
        principle="그래프 DB 는 데이터를 표가 아니라 노드(Node)와 관계(Relationship)로 저장합니다. Neo4j 는 노드가 이웃의 위치를 직접 가리키는 방식"
        "(Index-free Adjacency)이라, 관계를 여러 번 건너는 질의(Multi-hop)를 표 JOIN 없이 이웃을 따라가며 처리합니다. 질의 언어 Cypher 는 "
        "`(판례)-[:인용]->(조문)` 처럼 그래프 패턴을 그림처럼 씁니다. 노드 속성에 임베딩을 넣고 벡터 인덱스로 찾을 수도 있습니다.",
        why="관계형 DB 에서 '판례 → 인용 조문 → 그 조문을 위임한 시행령 → 그 시행령을 인용한 다른 판례' 같은 질의는 JOIN 이 단계마다 늘어 느려지고 쓰기도 어렵습니다. "
        "벡터 인덱스가 같은 DB 에 있으면 '비슷한 글 찾기'와 '연결 따라가기'를 한 질의로 합칠 수 있어 GraphRAG(K7)에 맞습니다.",
        how=[
            "(예정) Neo4j 를 docker compose 프로필로 추가(벡터 DB 들과 같은 방식), 온톨로지(K2)에서 제약 조건 · 인덱스 생성",
            "(예정) 그래프 저장소 인터페이스를 벡터 저장소처럼 두어 다른 그래프 DB 로 바꿀 수 있게",
            "(예정) Cypher 실습 화면: 역량 질문(K1)의 기대 쿼리를 실행해 결과 · 시간 확인",
        ],
        plans=["Neo4j docker 프로필 · 연결 설정 · 상태 확인", "법률 그래프 적재와 다단계 질의 실측(관계형 대비 시간)"],
        docs=[("지식 그래프 · GraphRAG 맵", "docs/kg-map.md")],
    ),
    Stage(
        key="text2cypher",
        builds_on=["agent"],
        no="K6",
        title="Text2Cypher",
        en="Natural language to graph query",
        status=PLANNED,
        flow="kg",
        map="kg",
        summary="질문을 LLM 이 Cypher 쿼리로 바꿔 그래프 DB 가 정확한 결과 · 집계를 돌려준다",
        principle="LLM 에 그래프 스키마(온톨로지)와 질문을 주고 Cypher 쿼리를 만들게 한 뒤, 그래프 DB 가 실행한 결과로 답합니다. "
        "숫자 · 목록 · 집계는 DB 가 계산하므로 LLM 이 지어낼 여지가 줄어듭니다.",
        why="'작년에 가장 많이 제기된 결함 유형은?', '제23조를 인용한 판례는 몇 건?' 같은 집계 · 필터 질문은 문서 조각을 읽는 벡터 RAG 로는 정확히 답하기 어렵습니다. "
        "대신 쿼리가 틀리면(없는 관계 이름 · 잘못된 방향) 결과가 비거나 엉뚱하므로, 생성한 쿼리를 검증하고 실패하면 다시 만드는 절차가 필요합니다.",
        how=[
            "(예정) 스키마 설명은 온톨로지(K2)에서 자동 생성, 읽기 전용 쿼리만 허용(쓰기 · 삭제 키워드 차단)",
            "(예정) 쿼리 검증: 문법 · 스키마에 있는 레이블 · 관계인지 확인, 결과가 비면 오류를 알려 다시 생성(최대 횟수 제한)",
            "(예정) 평가: 역량 질문의 기대 결과와 실행 결과 비교(정확 일치 · 집합 일치), 작은 로컬 LLM 과 큰 모델 비교",
        ],
        plans=["읽기 전용 Text2Cypher + 재시도", "역량 질문으로 쿼리 정확도 측정, LLM 크기별 비교"],
        docs=[("지식 그래프 · GraphRAG 맵", "docs/kg-map.md")],
    ),
    Stage(
        key="graph_hybrid",
        builds_on=["rag", "rerank"],
        no="K7",
        title="그래프 하이브리드 검색",
        short="하이브리드 검색",
        en="Vector + graph retrieval",
        status=PLANNED,
        flow="kg",
        map="kg",
        summary="벡터 검색으로 찾은 청크에서 연결된 개체 · 관계(서브그래프)를 함께 가져와 답변 맥락을 넓힌다",
        principle="질문과 비슷한 문서 청크를 벡터로 먼저 찾고(LLM 맵의 2 RAG 검색과 같음), 그 청크와 연결된 개체 · 관계를 그래프에서 한두 단계 따라가 "
        "'이 판례는 이 조문을 인용했고, 그 조문은 이 시행령에 위임했다' 같은 맥락을 근거에 덧붙입니다.",
        why="벡터 RAG 는 질문과 글이 비슷한 조각만 가져와, 답에 필요한 연결된 사실(다른 문서에 있는 관련 조문 · 판례)을 놓칩니다. "
        "법률 재측정에서 여러 문서 질문의 검색 nDCG 가 37 로 가장 낮았던 것이 이 한계입니다.",
        how=[
            "(예정) 1단계는 기존 RAG 검색(KURE · 하이브리드)을 그대로 쓰고, 결과 청크의 문서 노드에서 이웃(인용 조문 · 같은 쟁점 판례)을 확장",
            "(예정) 확장한 서브그래프를 근거에 '관계 요약' 으로 붙이고, 답변은 같은 인용 · 검증(근거 일치 · 질문 관련성) 규칙을 따름",
            "(예정) 평가: 여러 문서 질문 · 다단계 질문에서 벡터 RAG 와 짝지어 비교 — LLM 맵의 연결 비교에 경로로 추가",
        ],
        plans=["법률 그래프로 '검색 + 1단계 이웃 확장' 경로", "여러 문서 질문에서 벡터 RAG 대비 실측"],
        docs=[("지식 그래프 · GraphRAG 맵", "docs/kg-map.md"), ("LLM 맵 · 2 RAG 검색", "docs/stages/2-rag/rag.md")],
    ),
    Stage(
        key="community_summary",
        builds_on=["apps"],
        no="K8",
        title="글로벌 커뮤니티 요약",
        short="커뮤니티 요약",
        en="Global community summaries (GraphRAG)",
        status=PLANNED,
        flow="kg",
        map="kg",
        summary="그래프를 계층적 커뮤니티로 나눠 미리 요약해 두고, 전체 주제 · 추세 질문은 요약들을 모아 답한다",
        principle="그래프를 연결이 촘촘한 묶음(커뮤니티)으로 나누고(Leiden 등), 묶음마다 LLM 으로 요약을 미리 만들어 둡니다. 큰 묶음 안에 작은 묶음이 있는 계층 구조입니다. "
        "'이 자료 전체의 주요 쟁점은?' 같은 질문에는 특정 노드를 찾는 대신 관련 커뮤니티 요약들을 모아 답합니다(Microsoft GraphRAG 의 Global Search 방식).",
        why="벡터 RAG 와 Text2Cypher 는 모두 '어딘가에 있는 특정 사실'을 찾는 방식이라, 책 한 권 분량 전체를 훑어야 하는 요약 · 추세 질문에는 약합니다. "
        "대신 요약을 미리 만드는 비용이 크고(LLM 호출이 커뮤니티 수만큼), 자료가 바뀌면 다시 만들어야 합니다.",
        how=[
            "(예정) 커뮤니티 탐지 → 계층별 요약 생성(로컬 LLM, 작업으로 백그라운드 실행) → 요약 저장 · 색인",
            "(예정) 전체 질문은 커뮤니티 요약에서 답을 모으는 map-reduce, 근거로는 요약과 그 요약의 원문 노드를 인용",
            "(예정) 평가: '전체 요약' 질문을 따로 만들어 벡터 RAG 와 비교, 요약 생성 비용(시간 · 토큰) 기록",
        ],
        plans=["법률 그래프 커뮤니티 탐지 · 요약", "전체 요약 질문 평가 세트와 비용 측정"],
        docs=[("지식 그래프 · GraphRAG 맵", "docs/kg-map.md")],
    ),
    # ── 멀티에이전트 · 멀티모달 맵 (MA1~MA8) ────────────────────────────────────
    # 멀티모달 = 처리하는 데이터의 종류를 넓힘(앞단 입력 · 검색, 뒷단 출력), 멀티에이전트 = 처리 과정을 전문가 협업으로 넓힘(라우터 자리를 오케스트레이터가).
    # 이미 있는 것(멀티모달 임베딩 · 이미지 컬렉션 · 그림 근거 답변, 에이전트 도구, 라우팅 · 소형 모델, 답변 검증)을 상태에 그대로 반영한다.
    Stage(
        key="mm_input",
        no="MA1",
        title="멀티모달 입력 · 임베딩",
        short="멀티모달 임베딩",
        en="Multimodal input & embedding",
        status=BASIC,
        flow="agents",
        map="agents",
        builds_on=["multimodal", "embedding"],
        summary="텍스트 · 이미지 · 음성 · 문서를 공통 벡터 공간에 놓아, 사진으로 매뉴얼을 찾는 식의 교차 검색을 한다",
        principle="멀티모달 임베딩 모델(CLIP · SigLIP · ImageBind · 멀티모달 EmbeddingGemma 등)은 이미지와 텍스트(모델에 따라 음성까지)를 같은 벡터 공간에 놓습니다. "
        "그래서 이미지 자체를 질의로 써서 비슷한 텍스트 · 이미지를 찾을 수 있습니다(예: 제품 사진 → 관련 매뉴얼).",
        why="고객 · AS 문의는 '이 에러 화면' · '이 부품' 처럼 사진으로 들어오는 경우가 많습니다. 사진을 글로 옮겨 적게 하면 정보가 빠지고 사용자가 불편합니다.",
        how=[
            "(있음) LLM 맵 M 멀티모달: 이미지 · 영상 장면을 텍스트와 같은 공간에서 검색 — 한국어 질의는 EmbeddingGemma 2 가 CLIP 보다 크게 나음(실측 nDCG 100 vs 67.4)",
            "(예정) 이미지로 이미지 · 문서 찾기(질의 이미지 업로드), 사진 + 질문을 함께 넣는 질의",
            "(예정) 음성 입력: 음성 인식(STT)으로 글로 바꾼 뒤 같은 파이프라인, 오디오 임베딩은 의존성 해결 후",
        ],
        plans=["질의 이미지 업로드 검색", "음성 입력(STT) 연결"],
        docs=[("멀티에이전트 · 멀티모달 맵", "docs/agents-map.md"), ("LLM 맵 · 멀티모달", "docs/stages/multimodal/multimodal.md")],
    ),
    Stage(
        key="mm_rag",
        no="MA2",
        title="멀티모달 RAG",
        en="Multimodal RAG",
        status=BASIC,
        flow="agents",
        map="agents",
        builds_on=["rag", "multimodal", "rerank"],
        summary="표 · 그래프 · 설계도를 글로 바꾸지 않고 이미지 청크 그대로 저장 · 검색하고, 멀티모달로 다시 순위를 매긴다",
        principle="PDF 안의 복잡한 표 · 그래프 · 설계도는 글로 뽑으면 구조가 깨집니다. 페이지나 그림 영역을 이미지 청크로 그대로 저장해 멀티모달 임베딩으로 찾고, "
        "찾은 이미지는 비전 LLM 이 직접 읽어 답합니다.",
        why="사내 문서의 핵심 정보가 표 · 도면에 있는 경우가 많고, 텍스트 추출만으로는 '이 그래프의 추세'나 '도면의 부품 번호'를 답할 수 없습니다.",
        how=[
            "(있음) 이미지 · 영상 프레임을 RAG 컬렉션 문서로 올려 이미지 1장 = 청크 1개로 색인 · 검색, 근거 중 그림 청크를 비전 LLM(Gemma 4 + mmproj)에 첨부해 번호로 인용",
            "(예정) PDF 페이지 · 그림 영역을 이미지 청크로 함께 저장(텍스트 청크와 같은 문서에 묶어)",
            "(예정) 멀티모달 리랭킹: 질문과 이미지 후보를 함께 보는 리랭커 · 비전 LLM 목록형 재정렬",
        ],
        plans=["PDF 표 · 그림을 이미지 청크로", "멀티모달 리랭킹 실측"],
        docs=[("멀티에이전트 · 멀티모달 맵", "docs/agents-map.md"), ("LLM 연결 · 그림 근거 답변", "docs/guides/llm.md")],
    ),
    Stage(
        key="orchestrator",
        no="MA3",
        title="오케스트레이터 에이전트",
        short="오케스트레이터",
        en="Orchestrator agent",
        status=PLANNED,
        flow="agents",
        map="agents",
        builds_on=["routing", "agent"],
        summary="복잡한 요청을 작업으로 쪼개(Task Decomposition) 전문가 에이전트에게 나눠 주고 결과를 모은다 — 라우터 자리의 진화",
        principle="오케스트레이터는 '작년 분기별 매출 그래프를 분석해 보고서를 쓰고 요약해 줘' 같은 요청을 검색 → 분석 → 작성 → 검증 작업으로 나누고, "
        "작업마다 맞는 전문가 에이전트를 부르며, 중간 결과를 다음 작업에 넘깁니다. LLM 맵의 라우터가 '어느 경로로 보낼까'만 정했다면, 오케스트레이터는 '어떤 순서로 누구에게 무엇을' 정합니다.",
        why="하나의 모델이 검색 · 계산 · 글쓰기 · 검증을 다 하면 프롬프트가 길고 실패 지점이 섞여 어디서 틀렸는지 알 수 없습니다. 역할을 나누면 에이전트마다 작은 모델 · 도구 · 검증을 따로 고를 수 있습니다. "
        "다만 이 PC 의 실측에서 작은 로컬 모델은 여러 단계를 거친 답에서 근거 밖 문장이 늘었습니다(에이전트 문장 근거율 50% vs RAG 91%) — 단계를 늘릴수록 단계마다 검증이 필요합니다.",
        how=[
            "(있음) LLM 맵 6 라우팅(규칙 · 확신도 · LLM · 학습 라우터)과 8a 에이전트(ReAct · 도구)가 출발점",
            "(예정) 작업 계획을 JSON(작업 · 담당 에이전트 · 입력 · 의존)으로 받아 실행 · 기록, 단순한 질문은 지금처럼 RAG 한 번으로(계획 비용을 아끼게)",
            "(예정) 평가: 같은 질문을 단일 에이전트 · 멀티에이전트로 풀어 품질 · 시간 · 호출 수 비교",
        ],
        plans=["작업 계획(JSON) · 실행기 · 단계 기록", "단일 vs 멀티에이전트 실측"],
        docs=[("멀티에이전트 · 멀티모달 맵", "docs/agents-map.md"), ("LLM 맵 · 에이전트 실측", "docs/stages/8a-agent/agent.md")],
    ),
    Stage(
        key="retrieval_agent",
        no="MA4",
        title="검색 전문가 에이전트",
        short="검색 에이전트",
        en="Retrieval agent (Self-RAG)",
        status=BASIC,
        flow="agents",
        map="agents",
        builds_on=["agent", "search_lab", "rag"],
        summary="사내 문서 · 이미지 · 웹 검색만 맡고, 결과가 부실하면 스스로 질의를 고쳐 다시 찾는다(Self-RAG)",
        principle="검색 에이전트는 '정보 모으기'만 전담합니다. 찾은 결과가 질문에 충분한지 스스로 판단하고, 부족하면 질의를 바꾸거나 하위 질문으로 나눠 다시 검색합니다. "
        "모은 근거는 번호를 붙여 다음 에이전트에게 넘깁니다.",
        why="검색이 부실하면 뒤의 분석 · 작성이 아무리 좋아도 답이 틀립니다. 검색만 따로 두면 검색 품질을 기존 평가 세트(nDCG · 근거 검색률)로 따로 잴 수 있습니다.",
        how=[
            "(있음) 8a 에이전트의 search · read · lookup(조문 · 사건번호) 도구, 4 검색 향상(질의 재작성 · HyDE · 다중 질의), 2 RAG 하이브리드 검색",
            "(예정) 결과 충분성 판단 → 재검색 루프(상한), 이미지 · 웹 검색 도구 추가",
            "(예정) 평가: 재검색 전후 근거 검색률 · 질문당 검색 횟수",
        ],
        plans=["충분성 판단 · 재검색 루프", "이미지 · 웹 검색 도구"],
        docs=[("멀티에이전트 · 멀티모달 맵", "docs/agents-map.md")],
    ),
    Stage(
        key="analysis_agent",
        no="MA5",
        title="분석 · 코딩 에이전트",
        short="분석 에이전트",
        en="Analysis / code agent",
        status=PLANNED,
        flow="agents",
        map="agents",
        builds_on=["agent"],
        summary="검색된 표 · 수치를 파이썬 코드로 계산 · 검증하고 결과 차트를 만든다",
        principle="LLM 이 계산을 머릿속으로 하면 틀립니다. 분석 에이전트는 표 · 그래프 데이터를 파싱해 코드를 만들고, 격리된 실행기(코드 인터프리터)에서 실행한 결과로 통계 · 무결성 검증 · 차트를 냅니다.",
        why="'분기별 매출 증감률', '보증금 반환 금액 계산' 같은 질문은 숫자를 정확히 계산해야 합니다. 실행 결과를 근거로 쓰면 계산 과정을 재현 · 검증할 수 있습니다.",
        how=[
            "(있음) 8a 에이전트의 calc 도구 — 산술식만 계산(eval 없이, LLM 이 만든 코드를 실행하지 않음)",
            "(예정) 격리된 코드 실행기(시간 · 메모리 · 네트워크 제한, 허용 라이브러리만) — 임의 코드 실행 위험 때문에 격리가 먼저",
            "(예정) 표 파싱(PDF 표 · 이미지 표 → DataFrame), 결과 차트 생성(차트 색 규칙 · 색각이상 검증 그대로)",
        ],
        plans=["격리된 코드 실행기", "표 파싱 · 차트 생성"],
        docs=[("멀티에이전트 · 멀티모달 맵", "docs/agents-map.md")],
    ),
    Stage(
        key="report_agent",
        no="MA6",
        title="보고서 작성 에이전트",
        short="작성 에이전트",
        en="Writer agent (sLLM / LLM routing)",
        status=PLANNED,
        flow="agents",
        map="agents",
        builds_on=["routing", "distill", "quant"],
        summary="모은 근거 · 분석 결과로 정해진 형식의 답 · 보고서를 쓴다 — 쉬운 작성은 소형 모델, 어려운 작성은 큰 모델",
        principle="작성 에이전트는 근거와 분석 결과를 받아 템플릿(보고서 · 안내문 · 요약)에 맞춰 씁니다. 짧은 요약 · 정형 안내는 소형 모델(sLLM)로, 긴 종합 · 추론은 큰 모델로 보냅니다.",
        why="같은 품질이면 싼 모델을 써야 하지만, 작은 모델로 바꾸면 품질이 떨어질 수 있습니다. 이 PC 실측에서 Gemma 4 E2B 는 E4B 보다 지연 −21% 대신 품질 −13(유의)이라, 작성 난이도에 따라 나눠 써야 합니다.",
        how=[
            "(있음) 6 라우팅의 경로별 답변 모델 지정, 7b 양자화 · 7a 증류 실측(소형 모델 후보), 답변 원칙(질문에 대한 답 + 관련된 부가 설명만)",
            "(예정) 출력 템플릿(보고서 · AS 안내 · 요약)과 템플릿별 검증 규칙",
            "(예정) 작성 난이도 라우팅: 템플릿 · 근거 길이 · 요구 형식으로 sLLM / LLM 선택, 품질 · 비용 실측",
        ],
        plans=["출력 템플릿", "작성 난이도별 모델 라우팅 실측"],
        docs=[("멀티에이전트 · 멀티모달 맵", "docs/agents-map.md"), ("LLM 맵 · 소형 모델 실측", "docs/stages/7b-quant/quant.md")],
    ),
    Stage(
        key="critic_agent",
        no="MA7",
        title="품질 검증 에이전트",
        short="검증 에이전트",
        en="Critic / reviewer agent",
        status=BASIC,
        flow="agents",
        map="agents",
        builds_on=["rag", "rl"],
        summary="최종 답이 원문과 맞는지(환각) · 질문에 답하는지 · 보안 규정을 어기지 않는지 검사해 반려하거나 통과시킨다",
        principle="검증 에이전트는 답을 만들지 않고 검사만 합니다. 문장마다 근거 일치 · 질문 관련성 · 인용 번호를 확인하고, 규정(개인정보 · 내부 정보 노출 등)을 점검해 "
        "통과 / 수정 요청 / 반려를 정합니다. 반려되면 작성 에이전트가 이유를 받아 다시 씁니다(교차 검증).",
        why="에이전트가 많아질수록 앞 단계의 실수가 뒤로 전달됩니다. 마지막에 독립된 검사가 있어야 서비스로 내보낼 수 있습니다. "
        "다만 이 PC 의 사람 판정에서 작은 LLM 판정은 근거 일치를 28개 모두 통과시켰습니다 — 검증 에이전트는 LLM 판단만이 아니라 측정으로 보정된 점수를 함께 써야 합니다.",
        how=[
            "(있음) 답변 검증(근거 일치 · 질문 관련성 · 조문 · 판례 번호 검사), 사람 판정으로 보정(검증 보정 화면), 8b 보상 함수 · Best-of-N 으로 후보 고르기",
            "(예정) 검사 결과로 통과 / 수정 요청 / 반려 결정 → 작성 에이전트 재작성 루프(횟수 제한)",
            "(예정) 보안 규정 검사(개인정보 · 금지어 · 내부 문서 등급)",
        ],
        plans=["반려 · 재작성 루프", "보안 규정 검사"],
        docs=[("멀티에이전트 · 멀티모달 맵", "docs/agents-map.md"), ("LLM 맵 · 답변 원칙과 검증", "docs/stages/2-rag/rag.md")],
    ),
    Stage(
        key="mm_output",
        no="MA8",
        title="멀티모달 출력",
        en="Multimodal output",
        status=PLANNED,
        flow="agents",
        map="agents",
        builds_on=["multimodal"],
        summary="텍스트 답에 더해 차트 · 이미지 · 음성으로 결과를 낸다",
        principle="수집한 이미지 · 표 근거와 분석 결과를 함께 써서, 글 답변 외에 새 차트 · 요약 이미지 · 음성(TTS) 안내를 만듭니다. 출력도 근거 번호와 검증을 따릅니다.",
        why="'그래프로 보여 줘', '현장에서 들을 수 있게' 같은 요구는 글만으로 채울 수 없습니다. AS 수리 안내는 단계별 그림 · 음성이 더 쓸모 있습니다.",
        how=[
            "(있음) 그림 근거를 읽고 글로 답하기(비전 입력) — 출력은 아직 글만",
            "(예정) 분석 에이전트(MA5) 결과로 차트 출력, 음성 안내(TTS)",
            "(예정) 출력물에도 근거 번호를 달고 검증 에이전트(MA7)를 거침",
        ],
        plans=["차트 출력", "음성 안내(TTS)"],
        docs=[("멀티에이전트 · 멀티모달 맵", "docs/agents-map.md")],
    ),
]
BY_KEY = {s.key: s for s in STAGES}
MAIN_FLOW = [s for s in STAGES if s.flow == "main"]
EXTRA = [s for s in STAGES if s.flow == "extra"]
KG_FLOW = [s for s in STAGES if s.map == "kg"]
AGENTS_FLOW = [s for s in STAGES if s.map == "agents"]
OTHER_MAP_STAGES = [s for s in STAGES if s.map != "llm"]


def map_stages(key: str) -> list[Stage]:
    return [s for s in STAGES if s.map == key]


def map_flow(stage: Stage) -> list[Stage]:
    """이전 · 다음 단계를 잇는 흐름. LLM 맵은 본선만(곁가지 없음), 다른 맵은 그 맵의 단계 순서."""
    if stage.map == "llm":
        return MAIN_FLOW if stage.flow == "main" else []
    return map_stages(stage.map)


def stage_for_nav(nav: str | None) -> Stage | None:
    """화면의 nav 키 → 그 화면이 속한 단계 (상단 설명 패널용)."""
    if not nav:
        return None
    if nav.startswith("stage_"):
        return BY_KEY.get(nav[6:])
    return next((s for s in STAGES if any(p.nav == nav for p in s.pages)), None)
