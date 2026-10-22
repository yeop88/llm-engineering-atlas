"""LLM 생태계 구조(데이터만): 상위 그룹 A~F · 공통 노드 온톨로지 · 생태계 맵 M1~M30 · 확장 E1~E4 · 통합 라우팅.

맵이 28개를 넘으면서 '이 앱의 맵이 LLM 생태계의 어디를 덮고 어디가 비었나'를 한눈에 볼 수 없었다. 생태계 맵(M 번호)은 기술 영역의
목록이고, 이 앱의 맵(maps/<맵>.py)은 실행 구조다 — 둘을 같게 만들지 않고 대응표로 잇는다(생태계 맵 하나를 여러 앱 맵이 덮기도, 앱 맵 하나가
여러 생태계 맵에 걸치기도 한다). 구현 상태(앱 맵 단계의 상태)와 기술 성숙도(기초 · 성숙 · 신선 · 실험적)는 따로 적는다 — 성숙한 기술도
이 앱에서는 예정일 수 있고, 실험적 기술도 이 앱에 기초가 있을 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 기술 성숙도 — 구현 상태와 다른 축
MATURITY = ("기초", "성숙", "신선", "실험적")
# 근거 수준 — 이 생태계 항목의 설명을 무엇으로 확인했나(오래된 기술 정보를 가려내려고 last_verified_at 과 함께)
EVIDENCE = {"measured": "이 앱에서 실측", "implemented": "이 앱에 구현(실측 전)", "documented": "공개 문서 · 논문", "survey": "동향 정리"}

GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("A", "지식과 검색", ("RAG", "GraphRAG", "문서 지능", "메모리")),
    ("B", "모델과 추론", ("모델 구조", "추론 엔진", "양자화", "KV 캐시", "엣지 AI")),
    ("C", "에이전트", ("단일 에이전트", "멀티 에이전트", "도구 사용", "프로토콜", "컴퓨터 사용")),
    ("D", "멀티모달", ("이미지", "음성", "영상", "실시간 스트림", "생성 미디어")),
    ("E", "품질과 안전", ("평가", "가드레일", "보안", "관측성", "거버넌스")),
    ("F", "제품과 인프라", ("라우팅", "비용 최적화", "배포", "데이터 플라이휠", "사용자 경험")),
)
GROUP_TITLE = {g: t for g, t, _ in GROUPS}

# 공통 노드 온톨로지 — 맵마다 따로 만들어도 노드 종류는 하나로(맵 사이를 잇고 같은 질의로 찾으려고)
NODE_TYPES: tuple[tuple[str, str, str], ...] = (
    ("Capability", "AI 능력", "요약 · 추론 · 음성 인식"),
    ("Model", "기반 모델", "LLM · VLM · Speech LLM"),
    ("Method", "알고리즘 · 기법", "RAG · 양자화 · 추측 디코딩"),
    ("Component", "시스템 구성 요소", "검색기 · 리랭커 · 게이트웨이"),
    ("Framework", "구현 프레임워크", "에이전트 · 평가 · 서빙 프레임워크"),
    ("Protocol", "상호운용 규약", "도구 연결 · 에이전트 통신"),
    ("Provider", "서비스 제공 주체", "클라우드 · 모델 제공사"),
    ("Dataset", "학습 · 평가 데이터", "골든셋 · 선호 데이터"),
    ("Benchmark", "평가 기준", "정확성 · 지연 · 비용"),
    ("Risk", "시스템 위험", "프롬프트 인젝션 · 환각"),
    ("Control", "위험 통제", "샌드박스 · 정책 필터"),
    ("UseCase", "업무 사례", "상담원 · 검색 · 문서 처리"),
    ("Hardware", "실행 하드웨어", "GPU · NPU · 모바일"),
    ("Artifact", "실행 산출물", "프롬프트 · 임베딩 · 요청 기록"),
    ("Status", "구현 상태", "구현됨 · 기초 있음 · 예정 · 연구 · 보류"),
)
RELATIONS: tuple[tuple[str, str, str], ...] = (
    ("Model", "SUPPORTS", "Capability"),
    ("Method", "IMPROVES", "Benchmark"),
    ("Framework", "IMPLEMENTS", "Method"),
    ("Component", "CALLS", "Model"),
    ("Component", "USES_TOOL", "Component"),
    ("Protocol", "CONNECTS", "Component"),
    ("Risk", "MITIGATED_BY", "Control"),
    ("UseCase", "REQUIRES", "Capability"),
    ("Hardware", "RUNS", "Model"),
    ("Dataset", "EVALUATES", "Model"),
    ("Artifact", "GENERATED_BY", "Component"),
    ("Map", "DEPENDS_ON", "Map"),
    ("Map", "ROUTES_TO", "Map"),
)


@dataclass(frozen=True)
class EcoMap:
    """생태계 맵 하나. covers = 이 영역을 덮는 앱 맵 키(앞이 주), new = 이 영역을 위해 새로 만든 앱 맵 키(없으면 기존 맵이 덮음)."""

    id: str  # M1 ~ M30, E1 ~ E4
    title: str
    group: str  # A ~ F
    kind: str  # 기초 · 핵심 · 최적화 · 실용 · 신뢰성 · 제품 · 실시간 · 운영 · 실험적
    maturity: str
    priority: str  # 최우선 · 필수 · 높음 · 중간
    flow: str  # 생태계 문서의 흐름(요약)
    covers: tuple[str, ...] = ()
    new: str = ""
    metrics: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()  # 다른 생태계 맵 id
    note: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


ECOSYSTEM: tuple[EcoMap, ...] = (
    EcoMap("M1", "기반 모델 계보", "B", "기초", "기초", "필수", "모델 계열 → 세대 → 파라미터 · MoE → 컨텍스트 → 모달리티 → 라이선스",
           new="lineage", metrics=("모델 카드 확인율",), depends_on=("M2",)),
    EcoMap("M2", "Transformer · MoE 구조", "B", "기초", "성숙", "높음", "토큰화 → 임베딩 → 어텐션 → FFN · 전문가 → 라우팅 → 출력 헤드",
           covers=("interp", "bigmodel"), new="architecture", metrics=("활성 파라미터 비율", "토큰당 읽는 바이트"), depends_on=("M3",)),
    EcoMap("M3", "토크나이저 · 표현 공간", "B", "기초", "성숙", "중간", "정규화 → 분할 → 어휘 → 임베딩 → 위치 → 멀티모달 공통 공간",
           covers=("interp",), new="tokenizer", metrics=("한국어 글자당 토큰", "어휘 밖 비율")),
    EcoMap("M4", "학습 생애주기", "B", "기초", "성숙", "필수", "수집 → 전처리 · 중복 제거 → 사전학습 → 지시 튜닝 → 선호 정렬 → 안전 정렬 → 평가 → 배포",
           covers=("posttrain", "rlvr", "flywheel", "llm"), new="training", metrics=("누수율", "정렬 전후 품질"), depends_on=("M30",)),
    EcoMap("M5", "추론 · Reasoning", "B", "핵심", "신선", "높음", "문제 유형 → 즉답 · 숙고 라우팅 → 계획 → 도구 → 중간 검증 → 최종 답",
           covers=("reasoning",), metrics=("예산별 정답률", "pass@n"), depends_on=("M18", "M29"),
           note="생각 원문 저장보다 계획 · 도구 호출 · 검증 결과 · 최종 근거를 구조화해 남긴다(이 앱의 생각 검사 · 증류도 같은 원칙)"),
    EcoMap("M6", "기본 RAG", "A", "기초", "기초", "최우선", "수집 → 파싱 → 청킹 → 임베딩 → 벡터 검색 → 재정렬 → 맥락 → 답 → 인용 검증",
           covers=("llm",), metrics=("Recall@K", "NDCG", "근거 일치", "인용 정확도")),
    EcoMap("M7", "고급 RAG 검색 전략", "A", "최적화", "성숙", "높음", "질문 분석 → 재작성 → 검색 방식 선택(밀집 · 희소 · 혼합 · 메타 · 다중) → 재정렬 → 압축 → 근거 병합",
           covers=("llm", "context"), metrics=("방식별 Recall", "압축 후 정답률"), depends_on=("M6",)),
    EcoMap("M8", "GraphRAG · 지식 그래프", "A", "핵심", "성숙", "높음", "요구 → 온톨로지 → 추출 → 정규화 · 융합 → 저장 → Text2Query → 하위 그래프 → 커뮤니티 요약 → 근거",
           covers=("kg", "analytics"), metrics=("Text2Cypher · SQL 실행 정확도", "질문 유형별 정답률"), depends_on=("M6",)),
    EcoMap("M9", "문서 지능", "A", "실용", "성숙", "높음", "분류 → OCR · 레이아웃 → 표 · 그림 → 구조 복원 → 엔터티 → 문서 간 연결 → 색인",
           covers=("docintel",), metrics=("표 복원율", "OCR 글자 오류")),
    EcoMap("M10", "데이터 계보 · 근거", "A", "신뢰성", "성숙", "높음", "원본 → 수집 시각 → 변환 → 청크 → 주장 → 답 문장 → 인용 → 검증",
           covers=("evalops", "compliance"), new="provenance", metrics=("문장 → 원본 추적률", "모순 탐지"), depends_on=("M6", "M30")),
    EcoMap("M11", "대화 컨텍스트", "A", "기초", "기초", "필수", "재작성 → 모호성 → 되묻기 → 상태 갱신 → 답 → 후속 행동",
           covers=("conversation",), metrics=("재작성 후 Recall", "되묻기 적중")),
    EcoMap("M12", "장기 메모리", "A", "신선", "신선", "높음", "후보 추출 → 가치 평가 → 민감도 → 저장 → 감쇠 → 검색 → 적용 → 수정 · 삭제",
           covers=("memory", "conversation"), metrics=("갱신 질문 정답률", "맥락 글자"), risks=("memory_poisoning", "민감 정보 보존")),
    EcoMap("M13", "긴 컨텍스트 · 압축", "B", "최적화", "신선", "높음", "중복 제거 → 질문 인식 압축 → 대화 요약 → 중요 구간 → 싱크 · 창 → 중요 KV → KV 양자화 → 평가",
           covers=("compress", "context"), metrics=("압축률 × 정답률", "다음 토큰 일치"), depends_on=("M28",)),
    EcoMap("M14", "개인화 · 적응", "F", "제품", "신선", "중간", "동의 → 명시적 선호 → 행동 신호 → 프로필 갱신 → 응답 전략 → 개인화 응답 → 피드백",
           covers=("conversation", "memory"), new="personalize", metrics=("개인화 전후 만족", "동의 범위 위반 0"), risks=("동의 밖 사용",)),
    EcoMap("M15", "단일 에이전트 실행", "C", "기초", "성숙", "필수", "목표 → 계획 → 도구 선택 → 권한 → 실행 → 관찰 → 재계획 → 완료 검사 → 보고",
           covers=("longrun", "llm", "coding"), metrics=("완료율", "걸음 수")),
    EcoMap("M16", "멀티 에이전트 오케스트레이션", "C", "신선", "신선", "높음", "분해 → 역할 → 발견 → 위임 → 병렬 · 순차 → 검증 → 충돌 해결 → 통합",
           covers=("agents",), metrics=("단일 대비 정답률", "비용"), depends_on=("M15", "M17")),
    EcoMap("M17", "에이전트 프로토콜", "C", "핵심", "신선", "최우선", "신원 → 기능 · 도구 발견 → 메시지 → 작업 생성 → 상태 → 결과 · 아티팩트 → 오류 · 취소 → 감사",
           covers=("interop",), metrics=("위임 성공", "멱등 재시도"),
           note="에이전트 → 도구 · 데이터는 MCP, 에이전트 ↔ 에이전트 상태 있는 작업은 A2A, 고위험 거래는 별도 승인 · 결제 계층(M20)"),
    EcoMap("M18", "도구 · 함수 호출", "C", "기초", "성숙", "높음", "등록 → 스키마 검증 → 도구 검색 → 인수 → 권한 → 실행 → 구조화 → 오류 복구",
           covers=("interop", "longrun"), metrics=("인수 오류율", "재시도 예산")),
    EcoMap("M19", "컴퓨터 사용 에이전트", "C", "신선", "신선", "높음", "화면 인식 → 요소 탐지 → 행동 계획 → 클릭 · 입력 → 변화 관찰 → 완료 판정 → 증거",
           covers=("computer_use",), metrics=("과제 성공", "위험 행동 차단"), risks=("웹 인젝션", "과한 행동")),
    EcoMap("M20", "에이전트 경제 · 거래", "C", "실험적", "실험적", "중간", "서비스 발견 → 가격 비교 → 예산 정책 → 거래 승인 → 결제 · 에스크로 → 결과 검증 → 정산 → 분쟁",
           new="economy", metrics=("예산 초과 0", "승인 없는 거래 0"), risks=("상대 위장", "과지출"), depends_on=("M17",)),
    EcoMap("M21", "실시간 스트리밍 LLM", "D", "실시간", "신선", "높음", "스트림 입력 → 조각 → 부분 인식 → 상태 갱신 → 점진 추론 → 토큰 · 소리 스트리밍 → 중단 → 세션 복구",
           covers=("voice", "omni"), new="realtime", metrics=("TTFT", "첫 소리까지", "p95 · p99", "세션 복구율")),
    EcoMap("M22", "음성 에이전트", "D", "실시간", "신선", "높음", "음성 입력 → VAD → 화자 분리 → STT · Speech LLM → 대화 · 도구 → 응답 계획 → TTS → 끼어들기",
           covers=("voice", "omni"), metrics=("턴 지연 p95", "WER/CER", "끼어들기 성공"), depends_on=("M11", "M15", "M18", "M21", "M30"),
           note="구조 A(STT → LLM → TTS)는 이 앱에 있고 구조 B(Speech-to-Speech 통합 모델)는 비교 대상 — 목표 500ms · 800ms · 1.5초"),
    EcoMap("M23", "오디오 이해", "D", "신선", "신선", "중간", "음원 → 음성 · 음악 · 환경음 분리 → 화자 · 언어 → 이벤트 → 시간 구간 → 의미 표현 → 검색 · 요약",
           covers=("voice",), new="audio", metrics=("이벤트 F1", "화자 오류")),
    EcoMap("M24", "이미지 · Vision-Language", "D", "기초", "성숙", "높음", "이미지 → 전처리 → 객체 · 영역 → OCR → 관계 → 시각 질의응답 → 근거 영역",
           covers=("agents", "as_service", "llm"), new="vision", metrics=("VQA 정답률", "근거 영역 일치"),
           note="VLM 하나에 모든 책임을 주지 않고 탐지 · OCR · 규칙 엔진을 나눈다"),
    EcoMap("M25", "비디오 이해", "D", "신선", "신선", "높음", "수집 → 장면 분할 → 대표 프레임 → 객체 · 행동 추적 → 음성 · 자막 정렬 → 시공간 추론 → 이벤트 색인 → 검색 · 요약",
           covers=("omni", "agents"), new="video", metrics=("시점 질문 정답률", "키프레임 절약")),
    EcoMap("M26", "실시간 오디오 · 비디오 풀듀플렉스", "D", "실험적", "실험적", "중간", "연속 입력 → 화자 · 시선 · 대상 → 시간 상태 융합 → 발화 의도 → 끼어들 시점 → 동시 듣기 · 보기 · 말하기 → 전환 타이밍",
           covers=("omni", "voice"), new="duplex", metrics=("끼어듦 오탐", "응답 시점 오차"), depends_on=("M21", "M22", "M25")),
    EcoMap("M27", "생성 이미지 · 비디오 제작", "D", "실험적", "신선", "중간", "기획 → 장면 · 샷 → 캐릭터 · 스타일 → 생성 → 음성 · 음악 → 편집 → 품질 검사 → 출처 · 워터마크",
           new="genmedia", metrics=("프롬프트 준수", "캐릭터 일관성", "출처 기록률"), risks=("저작권 · 초상권",)),
    EcoMap("M28", "추론 최적화", "B", "최적화", "성숙", "최우선", "워크로드 측정 → 미리 채우기 · 생성 분리 → 양자화 → KV 관리 → 연속 배칭 → 앞부분 캐시 → 추측 디코딩 → 병렬화 → 품질 회귀",
           covers=("serving", "bigmodel", "compress", "edge"), new="inference", metrics=("p95 지연", "비용/성공 작업", "품질 통과율"),
           note="기준선 → 메모리 압력 완화 → 배칭 → 캐시 → 추측 디코딩 → 품질 확인 → 카나리 → 확대 — 양자화 형식은 모델 · 장치 · 맥락 · 동시 수마다 다르다"),
    EcoMap("M29", "모델 라우팅 · 비용 최적화", "F", "최적화", "신선", "높음", "요청 분류 → 위험도 → 품질 요구 → 지연 · 예산 → 후보 → 선택 → 실패 시 승격 → 비용 · 품질 기록",
           covers=("llm", "reasoning", "serving", "platform"), new="routing", metrics=("품질 유지 비용 절감", "승격률"), depends_on=("M28", "M30")),
    EcoMap("M30", "평가 · 관측 · 운영 플라이휠", "E", "운영", "성숙", "최우선", "요구 품질 → 골든셋 → 오프라인 평가 → 배포 게이트 → 트레이싱 → 이상 탐지 → 실패 수집 → 골든셋 갱신 → 재평가",
           covers=("evalops", "flywheel", "platform"), metrics=("회귀 차단", "실패 → 평가 반영 시간")),
    EcoMap("E1", "LLM 보안", "E", "핵심", "성숙", "최우선", "입력 → 인젝션 탐지 → 격리 → 권한 → 도구 정책 → 출력 검사 → 유출 검사 → 감사",
           covers=("guardrails", "computer_use", "interop"), metrics=("레드팀 차단율",), risks=("간접 인젝션", "도구 오염", "메모리 오염", "유출")),
    EcoMap("E2", "AI 거버넌스", "E", "운영", "성숙", "높음", "사용 사례 등록 → 위험 분류 → 데이터 · 모델 카드 → 평가 증거 → 승인 → 배포 → 모니터링 → 사고 대응",
           covers=("compliance", "guardrails")),
    EcoMap("E3", "합성 데이터", "B", "최적화", "신선", "중간", "부족 분석 → 전략 → 생성 → 다양성 검사 → 중복 · 오염 제거 → 인간 검토 → 학습 → 실제 데이터 평가",
           covers=("posttrain", "flywheel", "llm"), new="synthetic", metrics=("다양성", "누수 0", "실제 데이터 개선")),
    EcoMap("E4", "엣지 · 온디바이스 LLM", "B", "실용", "성숙", "높음", "모델 선택 → 증류 → INT4 · INT8 → 연산자 호환 → 변환 → NPU · GPU 백엔드 → 메모리 → 오프라인 → 전력 · 발열",
           covers=("edge", "bigmodel")),
)  # fmt: skip
ECO_BY_ID = {e.id: e for e in ECOSYSTEM}

# 통합 라우팅 — 입력 하나가 거치는 단계와 각 단계를 맡는 앱 맵
ROUTING: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("① 입력 모달리티 판정", "텍스트 · 이미지 · 음성 · 영상", ("omni", "vision", "voice")),
    ("② 질문 · 작업 유형 판정", "사실 검색 · 집계 · 관계 · 추세 · 깊은 추론 · 도구 실행 · 실시간 대화", ("routing", "llm")),
    (
        "③ 실행 맵 선택",
        "Vector RAG · GraphRAG · SQL · Reasoning · Agent · Voice · Video",
        ("llm", "kg", "analytics", "reasoning", "longrun", "voice", "video"),
    ),
    ("④ 모델 라우팅", "소형 · 대형 · 추론 · VLM · 음성 · 로컬", ("routing", "serving", "edge")),
    ("⑤ 정책 · 권한 검사", "입력 방어 · ACL · 도구 정책 · 승인", ("guardrails", "platform", "interop")),
    ("⑥ 실행", "검색 · 도구 · 에이전트 · 생성", ("llm", "agents", "longrun")),
    ("⑦ 근거 · 결과 검증", "인용 일치 · 질문 관련성 · 사실성 · 도구 결과 일치 · 안전성", ("llm", "provenance", "guardrails")),
    ("⑧ 관측 · 평가 · 메모리", "요청 기록 · 회귀 · 플라이휠 · 장기 메모리", ("evalops", "flywheel", "memory")),
)

# 설계 원칙(모든 생태계 맵 공통)
PRINCIPLES: tuple[str, ...] = (
    "맵은 제품 목록이 아니라 실행 구조를 중심으로",
    "모델 · 프레임워크 · 프로토콜 · 기법을 서로 다른 노드 종류로",
    "구현 상태와 기술 성숙도를 따로",
    "모든 답 문장을 원본 근거까지 거슬러 올라갈 수 있게",
    "벡터 RAG 와 GraphRAG 는 경쟁이 아니라 라우팅으로 고르는 보완 구조",
    "실시간 음성 · 영상은 모델 성능만이 아니라 전송 · 턴 제어 · 중단 · 세션 복구까지",
    "에이전트의 계획 · 정책 판단 · 행동 실행 · 감사 기록을 다른 모듈로",
    "최적화는 평균보다 p95 지연 · 성공 작업당 비용 · 품질 통과율",
    "모든 맵에 last_verified_at 과 evidence_level — 오래된 기술 정보를 가려내게",
)


# 앱 맵의 생태계 자리: 키 → (그룹, 성숙도, 기대는 앱 맵, 근거 수준). 생태계 번호(eco)는 위 대응표의 covers · new 에서 계산한다 — 두 곳에 적으면 어긋난다.
# 근거 수준: 실측이 문서에 있는 맵은 measured, 구현만 있고 실측 전이면 implemented.
APP_META: dict[str, tuple[str, str, tuple[str, ...], str]] = {
    "llm": ("A", "기초", (), "measured"),
    "kg": ("A", "성숙", ("llm",), "measured"),
    "agents": ("C", "신선", ("llm", "kg"), "measured"),
    "evalops": ("E", "성숙", ("llm",), "measured"),
    "guardrails": ("E", "성숙", ("llm",), "measured"),
    "docintel": ("A", "성숙", ("llm",), "measured"),
    "serving": ("B", "성숙", ("llm",), "measured"),
    "conversation": ("A", "기초", ("llm",), "measured"),
    "as_service": ("F", "기초", ("llm", "conversation", "guardrails"), "measured"),
    "posttrain": ("B", "성숙", ("llm", "flywheel"), "measured"),
    "flywheel": ("E", "성숙", ("evalops", "guardrails"), "measured"),
    "platform": ("F", "성숙", ("serving", "guardrails", "evalops"), "measured"),
    "interop": ("C", "신선", ("llm", "guardrails"), "measured"),
    "voice": ("D", "신선", ("as_service", "conversation"), "measured"),
    "compliance": ("E", "성숙", ("llm", "kg", "guardrails"), "measured"),
    "longrun": ("C", "신선", ("llm", "interop"), "measured"),
    "rlvr": ("B", "신선", ("posttrain", "kg"), "measured"),
    "edge": ("B", "성숙", ("llm", "serving"), "measured"),
    "reasoning": ("B", "신선", ("rlvr", "posttrain"), "measured"),
    "context": ("B", "신선", ("llm",), "measured"),
    "analytics": ("C", "신선", ("llm", "guardrails"), "measured"),
    "coding": ("C", "신선", ("llm",), "measured"),
    "computer_use": ("C", "신선", ("guardrails",), "measured"),
    "interp": ("B", "신선", ("posttrain", "llm"), "measured"),
    "memory": ("A", "신선", ("conversation",), "measured"),
    "compress": ("B", "신선", ("interp", "context"), "measured"),
    "omni": ("D", "신선", ("voice", "as_service", "conversation"), "measured"),
    "bigmodel": ("B", "성숙", ("serving", "edge"), "measured"),
}
LAST_VERIFIED = "2026-10-22"  # 이 표 전체를 마지막으로 확인한 날 — 맵마다 다르게 확인하면 맵 파일의 last_verified_at 이 앞선다


def eco_ids(map_key: str) -> tuple[str, ...]:
    """이 앱 맵이 덮는(또는 이 영역을 위해 만든) 생태계 맵 번호."""
    return tuple(e.id for e in ECOSYSTEM if map_key in e.covers or e.new == map_key)
