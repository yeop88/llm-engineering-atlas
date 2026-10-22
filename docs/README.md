<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 문서

LLM Engineering Atlas 의 문서는 **맵 → 단계** 순서로 정리되어 있습니다. 맵 28개 · 단계 197개. 모든 맵이 같은 규칙을 따릅니다 — 맵 이름 하나를 화면 주소(`/maps/<맵>`) · 개요(`maps/<맵>.md`) · 단계 폴더(`stages/<맵>/`)에 같이 씁니다.

## 구조

```
docs/
  README.md                               이 색인 (생성)
  maps/<맵>.md                            맵 개요 — 모든 맵에 같은 '단계' 표 (전용 화면이 있는 맵은 직접 쓴 개요 + 생성 표)
  stages/<맵>/<번호>-<이름>/README.md       단계 문서: 원리 · 왜 · 어떻게 · 화면 · 할 일 · 기반 단계 (생성)
  stages/<맵>/<번호>-<이름>/*.md            그 단계의 상세 문서 · 실측 기록 (직접 씀)
  guides/                                 여러 단계에 걸친 가이드 (아키텍처 · API · 화면 · 데이터 처리 · 배포 · LLM · 설치 · 문제 해결)
  records/                                단계 밖의 실측 · 정정 기록
```

- 단계 폴더 이름 = `<번호>-<이름>` (번호는 소문자, 이름은 레지스트리 키에서 맵 접두어를 뺀 것 — 예: `as1-intake`, `k1-requirements`, `m-multimodal`)
- 생성 문서(색인 · 단계 README · 공통 맵 개요 · 맵 개요의 단계 표)는 레지스트리(`app/stages/registry/`)를 고친 뒤 `uv run python scripts/gen_docs.py` 로 다시 만듭니다.
- 상태: ✅ 구현됨 · 🟡 기초 있음(기능은 다른 맵에 있고, 이 맵의 관점으로 묶은 화면 · 측정은 아직) · ⬜ 예정

## 맵

| 맵 | 무엇을 | 단계 | 개요 | 화면 |
|---|---|---|---|---|
| **LLM 시스템 엔지니어링 맵** | 임베딩 → RAG 검색 → 리랭킹 → 라우팅 → 소형/대형 모델 · 에이전트 — 문서 지식을 싸고 빠르고 정확하게 서비스하는 흐름 | 12 — ✅ 12 | [llm.md](maps/llm.md) | `/maps/llm` |
| **지식 그래프 · GraphRAG 맵** | 온톨로지 설계 → 추출 · 융합 → 그래프 DB → GraphRAG — 개념과 관계를 구조로 저장해 다단계 · 집계 · 전체 요약 질문에 답하는 흐름 | 8 — ✅ 8 | [knowledge-graph.md](maps/knowledge-graph.md) | `/maps/knowledge-graph` |
| **멀티에이전트 · 멀티모달 맵** | 멀티모달 입력 · 검색 → 오케스트레이터가 전문가 에이전트(검색 · 분석 · 작성 · 검증)에게 분배 → 교차 검증 → 텍스트 · 차트 · 음성 출력 | 8 — ✅ 8 | [multi-agent.md](maps/multi-agent.md) | `/maps/multi-agent` |
| **평가 · 관측 (LLMOps) 맵** | 평가 세트 → 오프라인 평가 · 회귀 → 트레이싱 → 피드백 → 드리프트 감지 · A/B → 개선 반영 — 서비스가 지금 잘 되고 있는지 숫자로 아는 흐름 | 8 — ✅ 8 | [evalops.md](maps/evalops.md) | `/maps/evalops` |
| **보안 · 가드레일 · 거버넌스 맵** | 입력 방어 → 개인정보 마스킹 → 권한별 검색 → 출력 정책 → 감사 로그 · 라이선스 · 레드팀 — 써도 되는 답인지 확인하는 흐름 | 7 — ✅ 7 | [guardrails.md](maps/guardrails.md) | `/maps/guardrails` |
| **문서 처리 (Document Intelligence) 맵** | 수집 → 파싱(HWP · PDF · OCR) → 레이아웃 · 표 · 그림 → 정제 · 중복 · 버전 → 청킹 → 메타데이터 · 증분 갱신 → 품질 점검 — 자료를 제대로 읽는 흐름 | 7 — ✅ 7 | [docintel.md](maps/docintel.md) | `/maps/docintel` |
| **서빙 · 추론 최적화 · 비용 맵** | 캐시 → 근거 길이 관리 → 경량 모델 → 추론 서버 · 배치 · 스트리밍 → KV 캐시 · 추측 디코딩 → 하드웨어 → 비용 · 지연 예산 — 싸고 빠르게 돌리는 흐름 | 7 — ✅ 7 | [serving.md](maps/serving.md) | `/maps/serving` |
| **대화 · 메모리 맵** | 대화 맥락 질의 재작성 → 되묻기 → 대화 요약 메모리 → 사용자 · 제품 프로필 → 긴 대화 압축 → 상담원 이관 — 한 번이 아니라 이어지는 상담을 다루는 흐름 | 6 — ✅ 6 | [conversation.md](maps/conversation.md) | `/maps/conversation` |
| **서비스 시나리오: 고객 AS 상담 맵** | 접수(텍스트 · 사진 · 음성) → 의도 · 긴급도 분류 → FAQ · 매뉴얼 답변 · 오류 사진 진단 → 조치 안내 → 검증 → 티켓 · 상담원 이관 → 피드백 — 기술 맵들을 실제 업무로 묶은 흐름 | 8 — ✅ 8 | [as-service.md](maps/as-service.md) | `/maps/as-service` |
| **후학습 (Post-training) 맵** | 합성 데이터 → 선별 · 누수 방지 → SFT → 선호 학습(DPO) → 어댑터 · 병합 → 평가 · 안전성 → 배포 형식 변환 — 우리 데이터로 LLM 자체를 고치는 흐름 | 7 — ✅ 7 | [posttrain.md](maps/posttrain.md) | `/maps/posttrain` |
| **데이터 플라이휠 맵** | 서비스 로그 → 실패 분류 → 사람 검토 → 평가 · 학습 데이터 → 재학습 → 게이트 → 단계적 배포 → 다시 로그 — 평가 · 후학습 · 서빙 · 가드레일을 하나의 순환으로 | 7 — ✅ 7 | [flywheel.md](maps/flywheel.md) | `/maps/flywheel` |
| **엔터프라이즈 AI 플랫폼 아키텍처 맵** | 게이트웨이 → 멀티테넌트 격리 → 모델 · 프롬프트 레지스트리 → 설정 · 기능 플래그 → 배포 → 장애 대응 · 대체 모델 → 비용 배분 — 맵들을 실제 운영 시스템으로 묶는 흐름 | 7 — ✅ 7 | [platform.md](maps/platform.md) | `/maps/platform` |
| **에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)** | 도구 정의 · 검색(MCP) → 권한 · 샌드박스 → 에이전트 간 위임(A2A) → 장기 작업 · 복구 → 호출 · 비용 상한 → 감사 추적 — 신뢰 경계를 넘나드는 에이전트 연결 | 6 — ✅ 6 | [interop.md](maps/interop.md) | `/maps/interop` |
| **실시간 음성 상담 맵** | 스트리밍 음성 인식 → 말 끊기 · 끼어들기 → 짧은 지연 RAG · 감정 감지 → 스트리밍 음성 합성 → 상담원 보조 · 통화 요약 — 전화 AS 상담 | 7 — ✅ 7 | [voice.md](maps/voice.md) | `/maps/voice` |
| **규제 대응 · 컴플라이언스 맵** | 적용 규제 식별 → 위험 등급 → 규정 조항 ↔ 시스템 통제 매핑 → 데이터 처리 근거 · 설명 가능성 · 고지 → 영향 평가 · 정기 감사 — 법 조항을 시스템 요구로 | 8 — ✅ 8 | [compliance.md](maps/compliance.md) | `/maps/compliance` |
| **장기 실행 에이전트 · 업무 자동화 맵** | 목표 분해 · 계획 → 실행 · 재계획 → 상태 저장 · 체크포인트 → 사람 승인 → 실패 복구 · 되돌리기 → 결과 검증 → 권한 · 비용 상한 — 며칠짜리 업무를 맡기는 흐름 | 7 — ✅ 7 | [longrun.md](maps/longrun.md) | `/maps/longrun` |
| **강화학습 기반 에이전트 학습 (RLVR) 맵** | 검증 가능한 과제 → 환경 · 도구 시뮬레이터 → 보상 설계 → 보상 해킹 감시 → 정책 학습(GRPO 등) → 일반화 · 안전성 평가 — 정답을 확인할 수 있는 과제로 에이전트를 학습 | 6 — ✅ 6 | [rlvr.md](maps/rlvr.md) | `/maps/rlvr` |
| **온디바이스 · 엣지 맵** | 기기별 모델 선택 → 극단적 양자화 · 증류 → 기기 내 검색 → 오프라인 동작 → 서버와 동기화 → 개인정보 국소 처리 — 서버 없이 기기에서 돌리는 흐름 | 6 — ✅ 6 | [edge.md](maps/edge.md) | `/maps/edge` |
| **추론 모델 · 테스트 시간 연산 맵** | 생각 예산 → 생각할지 말지 라우팅 → 여러 번 풀고 고르기 → 검증기 · 과정 보상 → 생각 과정 검사 → 추론 증류 — 생각하는 LLM 을 서비스에 쓰는 흐름 | 6 — ✅ 6 | [reasoning.md](maps/reasoning.md) | `/maps/reasoning` |
| **컨텍스트 엔지니어링 맵** | 맥락 예산 · 배치 → 긴 맥락 vs RAG → 도구 결과 · 기록 압축 → 프롬프트 캐시 → 외부 메모리 → 맥락 오염 방지 — 모델에 무엇을 얼마나 보여 줄지 설계하는 흐름 | 6 — ✅ 6 | [context.md](maps/context.md) | `/maps/context` |
| **데이터 분석 에이전트 · Text-to-SQL 맵** | 스키마 연결 → 지표 정의(의미 계층) → SQL 생성 → 실행 검증 · 고치기 → 결과 해석 · 차트 → 권한 · 안전 → 실행 정확도 평가 — 사내 DB 에 자연어로 묻는 흐름 | 7 — ✅ 7 | [analytics.md](maps/analytics.md) | `/maps/analytics` |
| **코딩 에이전트 · 소프트웨어 엔지니어링 맵** | 코드 검색 · 저장소 이해 → 작업 계획 → 수정 · 패치 → 테스트 실행 · 고치기 → 리뷰 · 보안 검사 → 해결률 평가 — 코드를 고치는 에이전트 | 6 — ✅ 6 | [coding.md](maps/coding.md) | `/maps/coding` |
| **컴퓨터 사용 · 브라우저 에이전트 맵** | 화면 이해 → 행동 계획 · 실행 → 상태 확인 → 위험 행동 승인 → 웹 콘텐츠 인젝션 방어 → 재생 평가 — 화면을 보고 클릭 · 입력하는 에이전트 | 6 — ✅ 6 | [computer-use.md](maps/computer-use.md) | `/maps/computer-use` |
| **해석 가능성 · 모델 내부 맵** | 임베딩 공간 분석 → 근거 기여 → 탐침 → 희소 특징 → 조종 · 편집 → 내부 신호 환각 탐지 — 모델이 왜 그렇게 답했는지 안을 보는 흐름 | 6 — ✅ 6 | [interp.md](maps/interp.md) | `/maps/interp` |
| **장기 메모리 · 메모리 DB 맵** | 대화에서 기억 뽑기 → 메모리 DB 저장 · 연결 → 관련 · 최근 · 중요도로 찾기 → 갱신 · 충돌 해결 → 통합 · 망각 → 메모리 계층 → 여러 세션 평가 — 긴 맥락을 DB 로 유지하는 흐름 | 7 — ✅ 7 | [memory.md](maps/memory.md) | `/maps/memory` |
| **프롬프트 · KV 캐시 압축 맵** | 토큰 단위 프롬프트 압축 → 질문을 아는 압축 → 주의 싱크 + 최근 창 → 중요 토큰 KV 남기기 → KV 양자화 → 압축률 vs 품질 평가 — 같은 모델로 더 긴 맥락을 싸게 | 6 — ✅ 6 | [compress.md](maps/compress.md) | `/maps/compress` |
| **옴니채널 · 실시간 멀티모달 에이전트 맵** | 채널 통합 세션 → 실시간 음성 대화 → 영상 스트림 분석 → 멀티모달 턴 융합 → 채널 간 이어 가기 → 비동기 메시지 처리 → 채널별 응답 형식 → 옴니 평가 — 전화 · 영상 · 메신저를 한 에이전트로 | 8 — ⬜ 8 | [omni.md](maps/omni.md) | `/maps/omni` |
| **적은 메모리로 큰 모델 돌리기 맵** | 메모리 계획 → 층 단위 스트리밍 → CPU-GPU 혼합 · 전문가 오프로드 → 페이지 KV 캐시 → 연속 배칭 → 극저비트 → 여러 기기 나눠 돌리기 — 메모리보다 큰 모델을 돌리는 흐름 | 7 — ⬜ 7 | [bigmodel.md](maps/bigmodel.md) | `/maps/bigmodel` |

## 가이드

- [아키텍처 — 코드 구조(core · stages · web)와 동작 방식](guides/architecture.md)
- [REST API](guides/api.md)
- [화면(UI) — 화면 뼈대 · 새 화면 만들기 · 부품 · 작업 맥락 · 스타일 · 접근성](guides/ui.md)
- [데이터 처리 — 수집 · 전처리 · 평가 자료 기록과 유효하게 처리하는 법](guides/data-processing.md)
- [배포 · 운영 — Docker, 접근 토큰, 작업 기록, 모델 호환성 점검, 새 모델 후보](guides/deploy.md)
- [LLM 연결 — 로컬 llama.cpp · OpenAI 호환 · Claude, 소형 모델 비교](guides/llm.md)
- [CPU · CUDA · ROCm 설치](guides/gpu.md)
- [문제 해결](guides/troubleshooting.md)

## 기록

- [대체 모델 정보 검증과 실측 벤치마크](records/model-verification.md)
- [파인튜닝 실행 기록 (#1~#3)](stages/llm/5-finetune/finetune.md#실행-기록)
- [벡터 검색 재현율 문제와 정정 기록](stages/llm/2-rag/rag.md#검색-정확도-정책-정확-검색--근사-검색)
