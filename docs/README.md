<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry.py)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 문서

LLM Engineering Atlas 의 문서는 맵의 단계 순서로 정리되어 있습니다. 맵은 [LLM 시스템 엔지니어링 맵](map.md) · [지식 그래프 · GraphRAG 맵](kg-map.md) · [멀티에이전트 · 멀티모달 맵](agents-map.md) · [평가 · 관측 (LLMOps) 맵](maps/evalops.md) · [보안 · 가드레일 · 거버넌스 맵](maps/guardrails.md) · [문서 처리 (Document Intelligence) 맵](maps/docintel.md) · [서빙 · 추론 최적화 · 비용 맵](maps/serving.md) · [대화 · 메모리 맵](maps/conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](maps/as-service.md) · [후학습 (Post-training) 맵](maps/posttrain.md) 입니다. 각 단계 폴더의 `README.md` 에 그 단계의 **원리 · 왜 하는가 · 어떻게(이 앱에서)** 가 있고, 같은 폴더에 상세 문서가 있습니다.

## LLM 시스템 엔지니어링 맵

임베딩 → RAG 검색 → 리랭킹 → 라우팅 → 소형/대형 모델 · 에이전트 — 문서 지식을 싸고 빠르고 정확하게 서비스하는 흐름

```
[데이터 임베딩] → [RAG 검색] → [리랭킹 (정밀 필터링)]
                                        ↓
[라우팅 (난이도 분류)] → 쉬운 질문:  [지식 증류 · 양자화된 소형 모델]
                       → 어려운 질문: [파인튜닝 · 강화학습된 에이전트 LLM]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| 1 | [데이터 임베딩](stages/1-embedding/README.md) | ✅ 구현됨 | 텍스트·이미지를 의미 벡터로 바꾸는 모델을 고르고 비교한다 | [모델 카탈로그](stages/1-embedding/models.md) · [벤치마크](stages/1-embedding/benchmarks.md) · [시각화](stages/1-embedding/visualization.md) |
| 2 | [RAG 검색](stages/2-rag/README.md) | ✅ 구현됨 | 내 문서에서 근거를 찾아 LLM 이 그 근거로 답하게 한다 | [문서 검색(RAG)](stages/2-rag/rag.md) · [LLM 연결](guides/llm.md) |
| 3 | [리랭킹](stages/3-rerank/README.md) | ✅ 구현됨 | 1단계 검색이 고른 후보를 정밀하게 다시 줄 세운다 | [리랭킹: 방법 · 실측](stages/3-rerank/rerank.md) |
| 4 | [검색 향상](stages/4-search-lab/README.md) | ✅ 구현됨 | 모델을 바꾸지 않고 질의를 LLM 으로 다듬어 검색을 좋게 한다 | [검색 향상: 기법 · 측정 기록](stages/4-search-lab/search-lab.md) |
| 5 | [파인튜닝](stages/5-finetune/README.md) | ✅ 구현됨 | 임베딩 모델을 내 문서 분야에 맞게 추가 학습한다 | [파인튜닝: 왜 · 어떻게 · 실행 기록](stages/5-finetune/finetune.md) |
| 6 | [라우팅](stages/6-routing/README.md) | ✅ 구현됨 | 질문의 난이도를 먼저 판단해 쉬운 질문은 싼 경로, 어려운 질문은 비싼 경로로 보낸다 | [라우팅: 라우터 · 평가 방법 · 실측](stages/6-routing/routing.md) |
| 7a | [지식 증류](stages/7a-distill/README.md) | ✅ 구현됨 | 큰 모델의 판단을 작은 모델이 따라 하도록 학습한다 | [지식 증류: 방법 · 실측](stages/7a-distill/distill.md) |
| 7b | [양자화](stages/7b-quant/README.md) | ✅ 구현됨 | 가중치 · 벡터를 낮은 비트로 바꿔 메모리와 지연을 줄이고, 정확도 손실을 잰다 | [양자화: 방법 · 실측](stages/7b-quant/quant.md) |
| 8a | [에이전틱 AI](stages/8a-agent/README.md) | ✅ 구현됨 | LLM 이 도구를 여러 번 써서 어려운 질문을 푼다 | [에이전트: 방법 · 실측](stages/8a-agent/agent.md) |
| 8b | [강화학습](stages/8b-rl/README.md) | ✅ 구현됨 | 보상 · 선호 신호로 답변 행동을 좋게 만든다 | [강화학습: 보상 · 방법 · 실측](stages/8b-rl/rl.md) |
| M | [멀티모달](stages/multimodal/README.md) | ✅ 구현됨 | 이미지 · 영상 장면을 텍스트와 같은 벡터 공간에서 찾는다 | [멀티모달: 모델 · 이미지 · 영상 컬렉션 · 실측](stages/multimodal/multimodal.md) |
| A | [의미 응용](stages/apps/README.md) | ✅ 구현됨 | 임베딩으로 추천 · 분류 · 군집 · 중복 · 이상 탐지 · 키워드를 만든다 | [의미 응용](stages/apps/apps.md) |

## 지식 그래프 · GraphRAG 맵

온톨로지 설계 → 추출 · 융합 → 그래프 DB → GraphRAG — 개념과 관계를 구조로 저장해 다단계 · 집계 · 전체 요약 질문에 답하는 흐름

```
[요구사항 정의] → [온톨로지 설계] → [데이터 추출 (ETL · LLM)] → [지식 융합 · 정제]
                                        ↓
                              [그래프 DB (Neo4j)]
                                        ↓
  GraphRAG: [Text2Cypher] · [그래프 하이브리드 검색] · [글로벌 커뮤니티 요약]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| K1 | [요구사항 정의](stages/kg/k1-requirements/README.md) | ⬜ 예정 | 지식 그래프가 답해야 할 업무 질문 10~15개로 그래프의 범위를 정한다 | — |
| K2 | [온톨로지 설계](stages/kg/k2-ontology/README.md) | ⬜ 예정 | 도메인의 개념(클래스) · 속성 · 관계와 그 규칙을 기계가 읽는 스키마로 정의한다 | — |
| K3 | [데이터 추출](stages/kg/k3-extract/README.md) | ⬜ 예정 | 정형 데이터는 스키마 매핑으로, 비정형 문서는 LLM 으로 [주어-관계-목적어] 트리플을 뽑는다 | — |
| K4 | [지식 융합 · 정제](stages/kg/k4-fusion/README.md) | ⬜ 예정 | 다른 이름의 같은 개체를 하나로 묶고(개체 정규화) 중복 · 충돌을 정리해 그래프를 완성한다 | — |
| K5 | [그래프 DB](stages/kg/k5-graph-db/README.md) | ⬜ 예정 | 노드와 관계로 저장하고, JOIN 없이 이웃을 따라가는 다단계 탐색과 벡터 검색을 한 곳에서 한다 | — |
| K6 | [Text2Cypher](stages/kg/k6-text2cypher/README.md) | ⬜ 예정 | 질문을 LLM 이 Cypher 쿼리로 바꿔 그래프 DB 가 정확한 결과 · 집계를 돌려준다 | — |
| K7 | [그래프 하이브리드 검색](stages/kg/k7-graph-hybrid/README.md) | ⬜ 예정 | 벡터 검색으로 찾은 청크에서 연결된 개체 · 관계(서브그래프)를 함께 가져와 답변 맥락을 넓힌다 | [LLM 맵 · 2 RAG 검색](stages/2-rag/rag.md) |
| K8 | [글로벌 커뮤니티 요약](stages/kg/k8-community-summary/README.md) | ⬜ 예정 | 그래프를 계층적 커뮤니티로 나눠 미리 요약해 두고, 전체 주제 · 추세 질문은 요약들을 모아 답한다 | — |

## 멀티에이전트 · 멀티모달 맵

멀티모달 입력 · 검색 → 오케스트레이터가 전문가 에이전트(검색 · 분석 · 작성 · 검증)에게 분배 → 교차 검증 → 텍스트 · 차트 · 음성 출력

```
[멀티모달 입력 (텍스트 · 이미지 · 음성 · 문서)] → [멀티모달 임베딩]
                                        ↓
                     [오케스트레이터 에이전트 (작업 분해 · 분배)]
          ↓                             ↓                              ↓
  [검색 전문가 (멀티모달 RAG)]   [분석 · 코딩 (표 · 코드 · 차트)]   [보고서 작성 (sLLM / LLM)]
                                        ↓
                     [품질 검증 (Critic) · 교차 검증]
                                        ↓
                [멀티모달 출력 (텍스트 + 차트 + 음성)]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| MA1 | [멀티모달 입력 · 임베딩](stages/agents/ma1-mm-input/README.md) | 🟡 기초 있음 | 텍스트 · 이미지 · 음성 · 문서를 공통 벡터 공간에 놓아, 사진으로 매뉴얼을 찾는 식의 교차 검색을 한다 | [LLM 맵 · 멀티모달](stages/multimodal/multimodal.md) |
| MA2 | [멀티모달 RAG](stages/agents/ma2-mm-rag/README.md) | 🟡 기초 있음 | 표 · 그래프 · 설계도를 글로 바꾸지 않고 이미지 청크 그대로 저장 · 검색하고, 멀티모달로 다시 순위를 매긴다 | [LLM 연결 · 그림 근거 답변](guides/llm.md) |
| MA3 | [오케스트레이터 에이전트](stages/agents/ma3-orchestrator/README.md) | ⬜ 예정 | 복잡한 요청을 작업으로 쪼개(Task Decomposition) 전문가 에이전트에게 나눠 주고 결과를 모은다 — 라우터 자리의 진화 | [LLM 맵 · 에이전트 실측](stages/8a-agent/agent.md) |
| MA4 | [검색 전문가 에이전트](stages/agents/ma4-retrieval-agent/README.md) | 🟡 기초 있음 | 사내 문서 · 이미지 · 웹 검색만 맡고, 결과가 부실하면 스스로 질의를 고쳐 다시 찾는다(Self-RAG) | — |
| MA5 | [분석 · 코딩 에이전트](stages/agents/ma5-analysis-agent/README.md) | ⬜ 예정 | 검색된 표 · 수치를 파이썬 코드로 계산 · 검증하고 결과 차트를 만든다 | — |
| MA6 | [보고서 작성 에이전트](stages/agents/ma6-report-agent/README.md) | ⬜ 예정 | 모은 근거 · 분석 결과로 정해진 형식의 답 · 보고서를 쓴다 — 쉬운 작성은 소형 모델, 어려운 작성은 큰 모델 | [LLM 맵 · 소형 모델 실측](stages/7b-quant/quant.md) |
| MA7 | [품질 검증 에이전트](stages/agents/ma7-critic-agent/README.md) | 🟡 기초 있음 | 최종 답이 원문과 맞는지(환각) · 질문에 답하는지 · 보안 규정을 어기지 않는지 검사해 반려하거나 통과시킨다 | [LLM 맵 · 답변 원칙과 검증](stages/2-rag/rag.md) |
| MA8 | [멀티모달 출력](stages/agents/ma8-mm-output/README.md) | ⬜ 예정 | 텍스트 답에 더해 차트 · 이미지 · 음성으로 결과를 낸다 | — |

## 평가 · 관측 (LLMOps) 맵

평가 세트 → 오프라인 평가 · 회귀 → 트레이싱 → 피드백 → 드리프트 감지 · A/B → 개선 반영 — 서비스가 지금 잘 되고 있는지 숫자로 아는 흐름

```
[평가 세트 · 정답] → [오프라인 평가 · 회귀] → [트레이싱]
                                      ↓
[비용 · 지연 대시보드] · [사용자 피드백 · 사람 판정] · [드리프트 감지] · [A/B 실험]
                                      ↓
                         [개선 반영 루프 (평가 세트 · 학습 데이터로)]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| E1 | [평가 세트 · 정답 관리](stages/evalops/e1-ev-sets/README.md) | 🟡 기초 있음 | 질문 · 정답 근거 · 질문 유형을 세트로 관리하고, 생성 · 보정 · 보충 기록을 남긴다 | — |
| E2 | [오프라인 평가 · 회귀](stages/evalops/e2-ev-offline/README.md) | 🟡 기초 있음 | 설정 · 모델 · 라이브러리를 바꿀 때마다 고정 세트로 다시 재서 기준선보다 나빠졌는지 확인한다 | — |
| E3 | [트레이싱](stages/evalops/e3-ev-tracing/README.md) | 🟡 기초 있음 | 질문마다 단계 · 시간 · 토큰 · 결정(라우팅 · 도구)을 기록해 한 요청을 끝까지 따라가 본다 | — |
| E4 | [비용 · 지연 대시보드](stages/evalops/e4-ev-cost/README.md) | ⬜ 예정 | 질문당 토큰 · 시간 · 비용을 모아 단계별 · 경로별로 보여 준다 | — |
| E5 | [사용자 피드백 · 사람 판정](stages/evalops/e5-ev-feedback/README.md) | 🟡 기초 있음 | 답변마다 좋아요 · 싫어요 · 이유를 받고, 사람 판정으로 자동 판정을 보정한다 | — |
| E6 | [드리프트 · 이상 감지](stages/evalops/e6-ev-drift/README.md) | ⬜ 예정 | 들어오는 질문의 분포 · 검색 확신도 · 거절률이 평소와 달라지면 알린다 | — |
| E7 | [A/B · 온라인 실험](stages/evalops/e7-ev-ab/README.md) | ⬜ 예정 | 실제 요청을 두 설정에 나눠 보내 품질 · 만족도 · 비용을 비교한다 | — |
| E8 | [개선 반영 루프](stages/evalops/e8-ev-loop/README.md) | ⬜ 예정 | 실패 사례를 모아 평가 세트 · 학습 데이터 · 규칙으로 되돌려 다음 버전을 만든다 | — |

## 보안 · 가드레일 · 거버넌스 맵

입력 방어 → 개인정보 마스킹 → 권한별 검색 → 출력 정책 → 감사 로그 · 라이선스 · 레드팀 — 써도 되는 답인지 확인하는 흐름

```
[입력 방어 (프롬프트 인젝션)] → [개인정보 탐지 · 마스킹] → [권한별 검색 (ACL)]
                                      ↓
             [출력 정책 검사] → [접근 제어 · 감사 로그]
                                      ↓
        [데이터 · 모델 라이선스 · 출처] · [레드팀 · 안전성 평가]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| G1 | [입력 방어 (프롬프트 인젝션)](stages/guardrails/g1-gr-injection/README.md) | ⬜ 예정 | 사용자 입력과 근거 문서 속에 숨은 지시가 LLM 을 조종하지 못하게 막는다 | — |
| G2 | [개인정보 탐지 · 마스킹](stages/guardrails/g2-gr-pii/README.md) | ⬜ 예정 | 주민번호 · 연락처 · 이름 같은 개인정보를 색인 전 · 답변 전에 찾아 가린다 | — |
| G3 | [권한별 검색 (ACL)](stages/guardrails/g3-gr-acl/README.md) | 🟡 기초 있음 | 사용자가 볼 수 있는 문서만 검색 후보에 넣는다 | — |
| G4 | [출력 정책 검사](stages/guardrails/g4-gr-output/README.md) | 🟡 기초 있음 | 답변이 근거 · 질문 · 정책을 어기지 않는지 내보내기 전에 검사한다 | — |
| G5 | [접근 제어 · 감사 로그](stages/guardrails/g5-gr-audit/README.md) | 🟡 기초 있음 | 누가 언제 무엇을 묻고 어떤 문서를 근거로 받았는지 남기고, 접근을 토큰 · 권한으로 막는다 | — |
| G6 | [데이터 · 모델 라이선스 · 출처](stages/guardrails/g6-gr-license/README.md) | 🟡 기초 있음 | 자료 · 모델마다 출처 · 라이선스 · 사용 조건을 기록하고 상업 사용 가능 여부를 확인한다 | — |
| G7 | [레드팀 · 안전성 평가](stages/guardrails/g7-gr-redteam/README.md) | ⬜ 예정 | 공격 · 유도 질문 세트로 방어가 실제로 동작하는지 정기적으로 잰다 | — |

## 문서 처리 (Document Intelligence) 맵

수집 → 파싱(HWP · PDF · OCR) → 레이아웃 · 표 · 그림 → 정제 · 중복 · 버전 → 청킹 → 메타데이터 · 증분 갱신 → 품질 점검 — 자료를 제대로 읽는 흐름

```
[수집 · 연결] → [파싱 (HWP · PDF · DOCX · OCR)] → [레이아웃 · 표 · 그림 추출]
                                      ↓
[정제 · 중복 · 버전] → [청킹] → [메타데이터 · 증분 갱신]
                                      ↓
                         [데이터 품질 점검]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| D1 | [수집 · 연결](stages/docintel/d1-doc-ingest/README.md) | 🟡 기초 있음 | 파일 업로드 · 공개 데이터 · 사내 시스템에서 원본을 가져오고 출처를 남긴다 | — |
| D2 | [파싱 (HWP · PDF · DOCX · OCR)](stages/docintel/d2-doc-parse/README.md) | 🟡 기초 있음 | 형식마다 맞는 파서로 글 · 구조를 뽑고, 스캔 문서는 OCR 로 읽는다 | — |
| D3 | [레이아웃 · 표 · 그림 추출](stages/docintel/d3-doc-layout/README.md) | ⬜ 예정 | 제목 · 단락 · 표 · 그림 영역을 나눠, 표는 구조로 · 그림은 이미지 청크로 남긴다 | — |
| D4 | [정제 · 중복 · 버전](stages/docintel/d4-doc-clean/README.md) | 🟡 기초 있음 | 머리말 · 반복 행 같은 잡음을 걷고, 거의 같은 문서 · 개정판을 정리한다 | — |
| D5 | [청킹](stages/docintel/d5-doc-chunk/README.md) | 🟡 기초 있음 | 문서를 검색 단위로 자르되 근거 문장이 경계에서 잘리지 않게 한다 | — |
| D6 | [메타데이터 · 증분 갱신](stages/docintel/d6-doc-meta/README.md) | ⬜ 예정 | 문서 날짜 · 종류 · 권한 메타데이터를 붙이고, 바뀐 문서만 다시 색인한다 | — |
| D7 | [데이터 품질 점검](stages/docintel/d7-doc-quality/README.md) | 🟡 기초 있음 | 처리 단계별 건수 · 길이 분포 · 근거 보존을 점검하고 처리 기록을 남긴다 | — |

## 서빙 · 추론 최적화 · 비용 맵

캐시 → 근거 길이 관리 → 경량 모델 → 추론 서버 · 배치 · 스트리밍 → KV 캐시 · 추측 디코딩 → 하드웨어 → 비용 · 지연 예산 — 싸고 빠르게 돌리는 흐름

```
[캐시 (의미 · 프롬프트 · 임베딩)] → [근거 길이 관리] → [경량 모델 (양자화 · 증류)]
                                      ↓
[추론 서버 · 배치 · 스트리밍] → [KV 캐시 · 추측 디코딩] → [하드웨어 배치]
                                      ↓
                         [비용 · 지연 예산]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| S1 | [캐시 (의미 · 프롬프트 · 임베딩)](stages/serving/s1-sv-cache/README.md) | 🟡 기초 있음 | 같거나 비슷한 계산을 다시 하지 않는다 — 임베딩 · LLM 변형 · 프롬프트 · 답변 캐시 | — |
| S2 | [근거 길이 관리](stages/serving/s2-sv-context/README.md) | 🟡 기초 있음 | LLM 이 읽을 근거의 수 · 길이를 품질을 지키는 범위에서 줄인다 | — |
| S3 | [경량 모델 (양자화 · 증류)](stages/serving/s3-sv-light/README.md) | 🟡 기초 있음 | 가중치 · 벡터 비트를 낮추고 작은 모델에 지식을 옮겨 메모리 · 지연을 줄인다 | — |
| S4 | [추론 서버 · 배치 · 스트리밍](stages/serving/s4-sv-server/README.md) | 🟡 기초 있음 | 모델별 서버 · 동시 처리 · 스트리밍으로 대기 시간과 처리량을 맞춘다 | — |
| S5 | [KV 캐시 · 추측 디코딩](stages/serving/s5-sv-decode/README.md) | ⬜ 예정 | KV 캐시 양자화로 긴 문맥 메모리를 줄이고, 추측 디코딩(MTP 등)으로 생성 속도를 올린다 | — |
| S6 | [하드웨어 배치](stages/serving/s6-sv-hardware/README.md) | 🟡 기초 있음 | 어느 모델을 CPU · 내장 GPU · 외장 GPU 에 둘지, 몇 개를 올려 둘지 정한다 | — |
| S7 | [비용 · 지연 예산](stages/serving/s7-sv-budget/README.md) | ⬜ 예정 | 질문당 비용 · p95 지연 목표를 정하고 경로 · 모델 · 근거 설정을 그 안에 맞춘다 | — |

## 대화 · 메모리 맵

대화 맥락 질의 재작성 → 되묻기 → 대화 요약 메모리 → 사용자 · 제품 프로필 → 긴 대화 압축 → 상담원 이관 — 한 번이 아니라 이어지는 상담을 다루는 흐름

```
[대화 맥락 질의 재작성] → [되묻기 (모호한 질문)] → [대화 요약 메모리]
                                      ↓
[사용자 · 제품 프로필] → [긴 대화 압축]
                                      ↓
                         [상담원 이관 · 인계 요약]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| C1 | [대화 맥락 질의 재작성](stages/conversation/c1-cv-rewrite/README.md) | ⬜ 예정 | '그거 말고 다른 모델은요?' 처럼 앞 대화를 가리키는 질문을 혼자 읽혀도 되는 질문으로 바꿔 검색한다 | — |
| C2 | [되묻기 (모호한 질문)](stages/conversation/c2-cv-clarify/README.md) | ⬜ 예정 | 질문이 모호하거나 정보가 모자라면 답하기 전에 필요한 것을 되묻는다 | — |
| C3 | [대화 요약 메모리](stages/conversation/c3-cv-memory/README.md) | ⬜ 예정 | 대화가 길어져도 중요한 사실(제품 · 증상 · 이미 해 본 조치)을 요약해 기억한다 | — |
| C4 | [사용자 · 제품 프로필](stages/conversation/c4-cv-profile/README.md) | ⬜ 예정 | 고객의 보유 제품 · 이전 문의 · 선호를 프로필로 두고 검색 · 답변에 쓴다 | — |
| C5 | [긴 대화 압축](stages/conversation/c5-cv-compress/README.md) | ⬜ 예정 | 긴 대화 · 긴 근거를 품질을 지키며 줄여 문맥 한도 안에 넣는다 | — |
| C6 | [상담원 이관 · 인계 요약](stages/conversation/c6-cv-handoff/README.md) | ⬜ 예정 | 자동으로 풀 수 없거나 위험한 문의는 대화 요약과 함께 사람에게 넘긴다 | — |

## 서비스 시나리오: 고객 AS 상담 맵

접수(텍스트 · 사진 · 음성) → 의도 · 긴급도 분류 → FAQ · 매뉴얼 답변 · 오류 사진 진단 → 조치 안내 → 검증 → 티켓 · 상담원 이관 → 피드백 — 기술 맵들을 실제 업무로 묶은 흐름

```
[문의 접수 (텍스트 · 사진 · 음성)] → [의도 · 긴급도 분류]
                    ↓                         ↓
       [FAQ · 매뉴얼 답변]          [오류 사진 진단]
                    └────────── ↓ ──────────┘
             [수리 · 조치 안내] → [품질 검증]
                                      ↓
        [접수 티켓 · 상담원 이관] → [피드백 · 개선]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| AS1 | [문의 접수 (텍스트 · 사진 · 음성)](stages/as-service/as1-as-intake/README.md) | ⬜ 예정 | 채팅 · 사진 · 음성 문의를 한 형식으로 받아 대화로 이어 간다 | — |
| AS2 | [의도 · 긴급도 분류](stages/as-service/as2-as-triage/README.md) | 🟡 기초 있음 | 문의 유형(고장 · 사용법 · 배송 · 환불)과 긴급도(안전 관련)를 나눠 처리 경로를 정한다 | — |
| AS3 | [FAQ · 매뉴얼 답변](stages/as-service/as3-as-faq/README.md) | 🟡 기초 있음 | 매뉴얼 · FAQ 에서 근거를 찾아 인용하며 답한다 — 쉬운 문의는 RAG 한 번 | — |
| AS4 | [오류 사진 진단](stages/as-service/as4-as-photo/README.md) | 🟡 기초 있음 | 오류 화면 · 부품 사진에서 오류 코드 · 증상을 읽고 매뉴얼의 해당 항목을 찾는다 | — |
| AS5 | [수리 · 조치 안내](stages/as-service/as5-as-guide/README.md) | ⬜ 예정 | 고객이 따라 할 수 있는 단계별 조치를 쓰고, 그림 · 음성으로도 낸다 | — |
| AS6 | [품질 검증](stages/as-service/as6-as-verify/README.md) | 🟡 기초 있음 | 안내가 매뉴얼과 맞는지 · 질문에 답하는지 · 안전 정책을 지키는지 확인한다 | — |
| AS7 | [접수 티켓 · 상담원 이관](stages/as-service/as7-as-ticket/README.md) | ⬜ 예정 | 해결되지 않으면 방문 · 수리 접수 티켓을 만들고 대화 요약과 함께 상담원에게 넘긴다 | — |
| AS8 | [피드백 · 개선](stages/as-service/as8-as-feedback/README.md) | ⬜ 예정 | 해결 여부 · 만족도를 받아 실패 사례를 평가 세트 · 매뉴얼 보강으로 되돌린다 | — |

## 후학습 (Post-training) 맵

합성 데이터 → 선별 · 누수 방지 → SFT → 선호 학습(DPO) → 어댑터 · 병합 → 평가 · 안전성 → 배포 형식 변환 — 우리 데이터로 LLM 자체를 고치는 흐름

```
[합성 데이터 생성] → [선별 · 누수 방지] → [SFT (지도 미세조정)]
                                      ↓
[선호 학습 (DPO 등)] → [어댑터 (LoRA) · 모델 병합]
                                      ↓
        [후학습 평가 · 안전성] → [배포 형식 변환 (GGUF · 양자화)]
```

| # | 단계 | 상태 | 무엇을 | 상세 문서 |
|---|---|---|---|---|
| P1 | [합성 데이터 생성](stages/posttrain/p1-pt-synth/README.md) | 🟡 기초 있음 | 큰 모델 · 규칙으로 질문 · 답 · 거절 예시를 만들어 학습 데이터를 늘린다 | — |
| P2 | [선별 · 누수 방지](stages/posttrain/p2-pt-select/README.md) | 🟡 기초 있음 | 검증을 통과한 좋은 예시만 남기고, 평가 세트의 근거가 학습에 섞이지 않게 한다 | — |
| P3 | [SFT (지도 미세조정)](stages/posttrain/p3-pt-sft/README.md) | ⬜ 예정 | 좋은 질문-답 예시로 LLM 을 추가 학습해 답 형식 · 인용 습관 · 도메인 말투를 맞춘다 | — |
| P4 | [선호 학습 (DPO 등)](stages/posttrain/p4-pt-pref/README.md) | ⬜ 예정 | 좋은 답 / 나쁜 답 쌍으로 모델이 좋은 쪽을 고르도록 학습한다 | — |
| P5 | [어댑터 (LoRA) · 모델 병합](stages/posttrain/p5-pt-adapter/README.md) | ⬜ 예정 | 분야별 어댑터를 따로 학습해 갈아 끼우거나, 여러 모델을 합쳐 장점을 모은다 | — |
| P6 | [후학습 평가 · 안전성](stages/posttrain/p6-pt-eval/README.md) | ⬜ 예정 | 학습 전후를 같은 평가 세트 · 같은 조건으로 비교하고, 안전성 회귀가 없는지 본다 | — |
| P7 | [배포 형식 변환 (GGUF · 양자화)](stages/posttrain/p7-pt-export/README.md) | 🟡 기초 있음 | 학습한 모델을 GGUF 로 바꾸고 양자화해 llama-server 에 올린다 | — |

## 가이드

- [아키텍처 — 코드 구조(core · stages · web)와 동작 방식](guides/architecture.md)
- [REST API](guides/api.md)
- [데이터 처리 — 수집 · 전처리 · 평가 자료 기록과 유효하게 처리하는 법](guides/data-processing.md)
- [배포 · 운영 — Docker, 접근 토큰, 작업 기록, 모델 호환성 점검, 새 모델 후보](guides/deploy.md)
- [LLM 연결 — 로컬 llama.cpp · OpenAI 호환 · Claude, 소형 모델 비교](guides/llm.md)
- [CPU · CUDA · ROCm 설치](guides/gpu.md)
- [문제 해결](guides/troubleshooting.md)

## 기록

- [대체 모델 정보 검증과 실측 벤치마크](records/model-verification.md)
- [파인튜닝 실행 기록 (#1~#3)](stages/5-finetune/finetune.md#실행-기록)
- [벡터 검색 재현율 문제와 정정 기록](stages/2-rag/rag.md#검색-정확도-정책-정확-검색--근사-검색)
