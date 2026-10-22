<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 문서

LLM Engineering Atlas 의 문서는 **맵 → 단계** 순서로 정리되어 있습니다. 맵 44개 · 단계 316개. 모든 맵이 같은 규칙을 따릅니다 — 맵 이름 하나를 화면 주소(`/maps/<맵>`) · 개요(`maps/<맵>.md`) · 단계 폴더(`stages/<맵>/`)에 같이 씁니다.

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
- 상태: ✅ 구현됨 · 🟡 기초 있음(기능은 다른 맵에 있고, 이 맵의 관점으로 묶은 화면 · 측정은 아직) · ⬜ 예정 · 🔬 연구(이 PC · 공개 모델로는 아직 제대로 돌릴 수 없어 설계 · 흉내 실험만) · ⏸ 보류
- 맵은 LLM 생태계 그룹 A~F 로 나뉩니다. 생태계 맵 34개(M1~M30 · E1~E4)와 이 앱의 맵의 대응 · 공통 온톨로지 · 통합 라우팅은 [LLM 생태계 구조](maps/ecosystem.md)에 있습니다.

## 맵

| 그룹 | 맵 | 무엇을 | 단계 | 개요 | 화면 |
|---|---|---|---|---|---|
| A | **LLM 시스템 엔지니어링 맵** | 임베딩 → RAG 검색 → 리랭킹 → 라우팅 → 소형/대형 모델 · 에이전트 — 문서 지식을 싸고 빠르고 정확하게 서비스하는 흐름 | 12 — ✅ 12 | [llm.md](maps/llm.md) | `/maps/llm` |
| A | **지식 그래프 · GraphRAG 맵** | 온톨로지 설계 → 추출 · 융합 → 그래프 DB → GraphRAG — 개념과 관계를 구조로 저장해 다단계 · 집계 · 전체 요약 질문에 답하는 흐름 | 8 — ✅ 8 | [knowledge-graph.md](maps/knowledge-graph.md) | `/maps/knowledge-graph` |
| A | **문서 처리 (Document Intelligence) 맵** | 수집 → 파싱(HWP · PDF · OCR) → 레이아웃 · 표 · 그림 → 정제 · 중복 · 버전 → 청킹 → 메타데이터 · 증분 갱신 → 품질 점검 — 자료를 제대로 읽는 흐름 | 7 — ✅ 7 | [docintel.md](maps/docintel.md) | `/maps/docintel` |
| A | **대화 · 메모리 맵** | 대화 맥락 질의 재작성 → 되묻기 → 대화 요약 메모리 → 사용자 · 제품 프로필 → 긴 대화 압축 → 상담원 이관 — 한 번이 아니라 이어지는 상담을 다루는 흐름 | 6 — ✅ 6 | [conversation.md](maps/conversation.md) | `/maps/conversation` |
| A | **장기 메모리 · 메모리 DB 맵** | 대화에서 기억 뽑기 → 메모리 DB 저장 · 연결 → 관련 · 최근 · 중요도로 찾기 → 갱신 · 충돌 해결 → 통합 · 망각 → 메모리 계층 → 여러 세션 평가 — 긴 맥락을 DB 로 유지하는 흐름 | 7 — ✅ 7 | [memory.md](maps/memory.md) | `/maps/memory` |
| A | **데이터 계보 · 근거 맵** | 원본 소스 → 수집 시각 → 변환 파이프라인 → 청크 → 주장 → 답 문장 → 인용 → 검증 결과 — 모든 답 문장을 원본까지 거슬러 올라가게 | 8 — ✅ 8 | [provenance.md](maps/provenance.md) | `/maps/provenance` |
| B | **서빙 · 추론 최적화 · 비용 맵** | 캐시 → 근거 길이 관리 → 경량 모델 → 추론 서버 · 배치 · 스트리밍 → KV 캐시 · 추측 디코딩 → 하드웨어 → 비용 · 지연 예산 — 싸고 빠르게 돌리는 흐름 | 7 — ✅ 7 | [serving.md](maps/serving.md) | `/maps/serving` |
| B | **후학습 (Post-training) 맵** | 합성 데이터 → 선별 · 누수 방지 → SFT → 선호 학습(DPO) → 어댑터 · 병합 → 평가 · 안전성 → 배포 형식 변환 — 우리 데이터로 LLM 자체를 고치는 흐름 | 7 — ✅ 7 | [posttrain.md](maps/posttrain.md) | `/maps/posttrain` |
| B | **강화학습 기반 에이전트 학습 (RLVR) 맵** | 검증 가능한 과제 → 환경 · 도구 시뮬레이터 → 보상 설계 → 보상 해킹 감시 → 정책 학습(GRPO 등) → 일반화 · 안전성 평가 — 정답을 확인할 수 있는 과제로 에이전트를 학습 | 6 — ✅ 6 | [rlvr.md](maps/rlvr.md) | `/maps/rlvr` |
| B | **온디바이스 · 엣지 맵** | 기기별 모델 선택 → 극단적 양자화 · 증류 → 기기 내 검색 → 오프라인 동작 → 서버와 동기화 → 개인정보 국소 처리 — 서버 없이 기기에서 돌리는 흐름 | 6 — ✅ 6 | [edge.md](maps/edge.md) | `/maps/edge` |
| B | **추론 모델 · 테스트 시간 연산 맵** | 생각 예산 → 생각할지 말지 라우팅 → 여러 번 풀고 고르기 → 검증기 · 과정 보상 → 생각 과정 검사 → 추론 증류 — 생각하는 LLM 을 서비스에 쓰는 흐름 | 6 — ✅ 6 | [reasoning.md](maps/reasoning.md) | `/maps/reasoning` |
| B | **컨텍스트 엔지니어링 맵** | 맥락 예산 · 배치 → 긴 맥락 vs RAG → 도구 결과 · 기록 압축 → 프롬프트 캐시 → 외부 메모리 → 맥락 오염 방지 — 모델에 무엇을 얼마나 보여 줄지 설계하는 흐름 | 6 — ✅ 6 | [context.md](maps/context.md) | `/maps/context` |
| B | **해석 가능성 · 모델 내부 맵** | 임베딩 공간 분석 → 근거 기여 → 탐침 → 희소 특징 → 조종 · 편집 → 내부 신호 환각 탐지 — 모델이 왜 그렇게 답했는지 안을 보는 흐름 | 6 — ✅ 6 | [interp.md](maps/interp.md) | `/maps/interp` |
| B | **프롬프트 · KV 캐시 압축 맵** | 토큰 단위 프롬프트 압축 → 질문을 아는 압축 → 주의 싱크 + 최근 창 → 중요 토큰 KV 남기기 → KV 양자화 → 압축률 vs 품질 평가 — 같은 모델로 더 긴 맥락을 싸게 | 6 — ✅ 6 | [compress.md](maps/compress.md) | `/maps/compress` |
| B | **적은 메모리로 큰 모델 돌리기 맵** | 메모리 계획 → 층 단위 스트리밍 → CPU-GPU 혼합 · 전문가 오프로드 → 페이지 KV 캐시 → 연속 배칭 → 극저비트 → 여러 기기 나눠 돌리기 — 메모리보다 큰 모델을 돌리는 흐름 | 7 — ✅ 7 | [bigmodel.md](maps/bigmodel.md) | `/maps/bigmodel` |
| B | **기반 모델 계보 맵** | 모델 계열 → 세대 → 파라미터 · MoE 구조 → 컨텍스트 길이 → 입력 · 출력 모달리티 → 라이선스 · 배포 조건 — 어떤 모델이 어떤 기능 · 환경에 맞나 | 6 — ⬜ 6 | [lineage.md](maps/lineage.md) | `/maps/lineage` |
| B | **Transformer · MoE 구조 맵** | 토큰화 → 임베딩 → 어텐션 → FFN · 전문가 → 라우팅 → 출력 헤드 — 밀집 · MoE · 슬라이딩 창 · 선형 어텐션 · 상태 공간이 메모리 · 연산에 미치는 영향 | 6 — ⬜ 6 | [architecture.md](maps/architecture.md) | `/maps/architecture` |
| B | **토크나이저 · 표현 공간 맵** | 원문 정규화 → 토큰 분할 → 어휘 → 임베딩 → 위치 표현 → 멀티모달 공통 공간 — 한국어 토큰 효율 · 코드 · 이미지 패치 · 오디오 토큰 | 6 — ⬜ 6 | [tokenizer.md](maps/tokenizer.md) | `/maps/tokenizer` |
| B | **학습 생애주기 맵** | 데이터 수집 → 전처리 · 중복 제거 → 사전학습 → 지시 튜닝 → 선호 정렬 → 안전 정렬 → 평가 → 배포 — 후학습 · RLVR · 플라이휠을 한 생애주기로 | 8 — ⬜ 7 · 🔬 1 | [training.md](maps/training.md) | `/maps/training` |
| B | **추론 최적화 맵** | 워크로드 측정 → 미리 채우기 · 생성 분리 → 양자화 → KV 캐시 관리 → 연속 배칭 → 앞부분 캐시 → 추측 디코딩 → 병렬화 → 품질 회귀 — 기준선부터 카나리까지 한 순서로 | 9 — ✅ 9 | [inference.md](maps/inference.md) | `/maps/inference` |
| B | **합성 데이터 맵** | 데이터 부족 분석 → 생성 전략 → 합성 데이터 생성 → 다양성 검사 → 중복 · 오염 제거 → 인간 검토 → 학습 → 실제 데이터 평가 — 합성으로 늘리되 실제로 잰다 | 8 — ⬜ 8 | [synthetic.md](maps/synthetic.md) | `/maps/synthetic` |
| C | **멀티에이전트 · 멀티모달 맵** | 멀티모달 입력 · 검색 → 오케스트레이터가 전문가 에이전트(검색 · 분석 · 작성 · 검증)에게 분배 → 교차 검증 → 텍스트 · 차트 · 음성 출력 | 8 — ✅ 8 | [multi-agent.md](maps/multi-agent.md) | `/maps/multi-agent` |
| C | **에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)** | 도구 정의 · 검색(MCP) → 권한 · 샌드박스 → 에이전트 간 위임(A2A) → 장기 작업 · 복구 → 호출 · 비용 상한 → 감사 추적 — 신뢰 경계를 넘나드는 에이전트 연결 | 6 — ✅ 6 | [interop.md](maps/interop.md) | `/maps/interop` |
| C | **장기 실행 에이전트 · 업무 자동화 맵** | 목표 분해 · 계획 → 실행 · 재계획 → 상태 저장 · 체크포인트 → 사람 승인 → 실패 복구 · 되돌리기 → 결과 검증 → 권한 · 비용 상한 — 며칠짜리 업무를 맡기는 흐름 | 7 — ✅ 7 | [longrun.md](maps/longrun.md) | `/maps/longrun` |
| C | **데이터 분석 에이전트 · Text-to-SQL 맵** | 스키마 연결 → 지표 정의(의미 계층) → SQL 생성 → 실행 검증 · 고치기 → 결과 해석 · 차트 → 권한 · 안전 → 실행 정확도 평가 — 사내 DB 에 자연어로 묻는 흐름 | 7 — ✅ 7 | [analytics.md](maps/analytics.md) | `/maps/analytics` |
| C | **코딩 에이전트 · 소프트웨어 엔지니어링 맵** | 코드 검색 · 저장소 이해 → 작업 계획 → 수정 · 패치 → 테스트 실행 · 고치기 → 리뷰 · 보안 검사 → 해결률 평가 — 코드를 고치는 에이전트 | 6 — ✅ 6 | [coding.md](maps/coding.md) | `/maps/coding` |
| C | **컴퓨터 사용 · 브라우저 에이전트 맵** | 화면 이해 → 행동 계획 · 실행 → 상태 확인 → 위험 행동 승인 → 웹 콘텐츠 인젝션 방어 → 재생 평가 — 화면을 보고 클릭 · 입력하는 에이전트 | 6 — ✅ 6 | [computer-use.md](maps/computer-use.md) | `/maps/computer-use` |
| C | **에이전트 경제 · 거래 맵** | 서비스 발견 → 가격 · 조건 비교 → 예산 정책 → 거래 승인 → 결제 · 에스크로 → 결과 검증 → 정산 → 분쟁 처리 — 에이전트가 돈을 쓰기 전에 지켜야 할 것 | 8 — 🔬 8 | [economy.md](maps/economy.md) | `/maps/economy` |
| D | **실시간 음성 상담 맵** | 스트리밍 음성 인식 → 말 끊기 · 끼어들기 → 짧은 지연 RAG · 감정 감지 → 스트리밍 음성 합성 → 상담원 보조 · 통화 요약 — 전화 AS 상담 | 7 — ✅ 7 | [voice.md](maps/voice.md) | `/maps/voice` |
| D | **옴니채널 · 실시간 멀티모달 에이전트 맵** | 채널 통합 세션 → 실시간 음성 대화 → 영상 스트림 분석 → 멀티모달 턴 융합 → 채널 간 이어 가기 → 비동기 메시지 처리 → 채널별 응답 형식 → 옴니 평가 — 전화 · 영상 · 메신저를 한 에이전트로 | 8 — ✅ 8 | [omni.md](maps/omni.md) | `/maps/omni` |
| D | **실시간 스트리밍 LLM 맵** | 스트림 입력 → 조각 나누기 → 부분 인식 → 상태 갱신 → 점진 추론 → 토큰 · 소리 스트리밍 → 중단 처리 → 세션 복구 — TTFT · 첫 소리 · p95 · p99 · 복구율 | 8 — ⬜ 8 | [realtime.md](maps/realtime.md) | `/maps/realtime` |
| D | **오디오 이해 맵** | 음원 입력 → 음성 · 음악 · 환경음 분리 → 화자 · 언어 → 이벤트 인식 → 시간 구간 → 의미 표현 → 검색 · 요약 — 말 이외의 소리까지 | 7 — ⬜ 5 · 🔬 2 | [audio.md](maps/audio.md) | `/maps/audio` |
| D | **이미지 · Vision-Language 맵** | 이미지 입력 → 전처리 → 객체 · 영역 → OCR → 관계 추론 → 시각 질의응답 → 근거 영역 표시 — VLM 하나에 다 맡기지 않고 탐지 · OCR · 규칙을 나눠서 | 7 — ⬜ 7 | [vision.md](maps/vision.md) | `/maps/vision` |
| D | **비디오 이해 맵** | 영상 수집 → 장면 분할 → 대표 프레임 → 객체 · 행동 추적 → 음성 · 자막 정렬 → 시공간 추론 → 이벤트 색인 → 검색 · 요약 — '처음 일어난 때' 에 답하기 | 8 — ⬜ 7 · 🔬 1 | [video.md](maps/video.md) | `/maps/video` |
| D | **실시간 오디오 · 비디오 풀듀플렉스 맵** | 연속 오디오 · 비디오 → 화자 · 시선 · 대상 추적 → 시간 상태 융합 → 발화 의도 예측 → 끼어들 시점 → 동시 듣기 · 보기 · 말하기 → 전환 타이밍 — 내용 이해와 대화 타이밍을 나눠서 | 7 — 🔬 7 | [duplex.md](maps/duplex.md) | `/maps/duplex` |
| D | **생성 이미지 · 비디오 제작 맵** | 기획 · 스크립트 → 장면 · 샷 분해 → 캐릭터 · 스타일 → 이미지 · 비디오 생성 → 음성 · 음악 → 편집 · 합성 → 품질 검사 → 출처 · 워터마크 — 만드는 것보다 검사 · 출처 | 8 — ⬜ 2 · 🔬 6 | [genmedia.md](maps/genmedia.md) | `/maps/genmedia` |
| E | **평가 · 관측 (LLMOps) 맵** | 평가 세트 → 오프라인 평가 · 회귀 → 트레이싱 → 피드백 → 드리프트 감지 · A/B → 개선 반영 — 서비스가 지금 잘 되고 있는지 숫자로 아는 흐름 | 8 — ✅ 8 | [evalops.md](maps/evalops.md) | `/maps/evalops` |
| E | **보안 · 가드레일 · 거버넌스 맵** | 입력 방어 → 개인정보 마스킹 → 권한별 검색 → 출력 정책 → 감사 로그 · 라이선스 · 레드팀 — 써도 되는 답인지 확인하는 흐름 | 7 — ✅ 7 | [guardrails.md](maps/guardrails.md) | `/maps/guardrails` |
| E | **데이터 플라이휠 맵** | 서비스 로그 → 실패 분류 → 사람 검토 → 평가 · 학습 데이터 → 재학습 → 게이트 → 단계적 배포 → 다시 로그 — 평가 · 후학습 · 서빙 · 가드레일을 하나의 순환으로 | 7 — ✅ 7 | [flywheel.md](maps/flywheel.md) | `/maps/flywheel` |
| E | **규제 대응 · 컴플라이언스 맵** | 적용 규제 식별 → 위험 등급 → 규정 조항 ↔ 시스템 통제 매핑 → 데이터 처리 근거 · 설명 가능성 · 고지 → 영향 평가 · 정기 감사 — 법 조항을 시스템 요구로 | 8 — ✅ 8 | [compliance.md](maps/compliance.md) | `/maps/compliance` |
| F | **서비스 시나리오: 고객 AS 상담 맵** | 접수(텍스트 · 사진 · 음성) → 의도 · 긴급도 분류 → FAQ · 매뉴얼 답변 · 오류 사진 진단 → 조치 안내 → 검증 → 티켓 · 상담원 이관 → 피드백 — 기술 맵들을 실제 업무로 묶은 흐름 | 8 — ✅ 8 | [as-service.md](maps/as-service.md) | `/maps/as-service` |
| F | **엔터프라이즈 AI 플랫폼 아키텍처 맵** | 게이트웨이 → 멀티테넌트 격리 → 모델 · 프롬프트 레지스트리 → 설정 · 기능 플래그 → 배포 → 장애 대응 · 대체 모델 → 비용 배분 — 맵들을 실제 운영 시스템으로 묶는 흐름 | 7 — ✅ 7 | [platform.md](maps/platform.md) | `/maps/platform` |
| F | **개인화 · 적응 맵** | 사용자 동의 → 명시적 선호 → 행동 신호 → 프로필 갱신 → 응답 전략 → 개인화 응답 → 피드백 — 개인화 데이터 · 인증 · 민감 정보 · 학습 동의를 나눠서 | 7 — ⬜ 7 | [personalize.md](maps/personalize.md) | `/maps/personalize` |
| F | **모델 라우팅 · 비용 최적화 맵** | 요청 분류 → 위험도 판정 → 품질 요구 → 지연 · 예산 → 모델 후보 → 모델 선택 → 실패 시 승격 → 비용 · 품질 기록 — 점수 = 품질 · 근거 · 지연 · 비용 · 신뢰성 | 8 — ✅ 8 | [routing.md](maps/routing.md) | `/maps/routing` |

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
