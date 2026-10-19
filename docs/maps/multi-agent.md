# 멀티에이전트 · 멀티모달 맵

세 번째 맵입니다. [LLM 시스템 엔지니어링 맵](llm.md)의 RAG 파이프라인을 두 방향으로 넓힙니다.

- **멀티모달**: 처리하는 **데이터의 종류**(텍스트 · 이미지 · 표 · 음성)를 넓혀 시스템에 눈과 귀를 줍니다. 파이프라인의 맨 앞(입력 · 임베딩 · 검색)과 맨 뒤(답변 생성 · 출력)에 들어갑니다.
- **멀티에이전트**: **처리 과정**(검색 · 분석 · 작성 · 검증)을 자율적인 전문가 협업으로 넓힙니다. LLM 맵의 라우터 자리(컨트롤 타워)를 오케스트레이터가 이어받고, 수행 단계 전체에 전문가 에이전트가 들어갑니다.

앱의 **맵 → 멀티에이전트 · 멀티모달 맵**(`/maps/multi-agent`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. 화면 문구와 단계별 README 는 단계 레지스트리(`app/stages/registry/`)에서 만들어집니다. 다른 맵과 달리 이 맵은 **이미 구현한 기능 위에** 짓는 단계가 많아, 단계마다 상태(구현됨 · 기초 있음 · 예정)와 **기반 단계**(LLM 맵의 어느 단계를 쓰는지)를 함께 적었습니다.

## 전체 흐름

```
[사용자 입력 (텍스트 · 이미지 · 음성 · 문서)]                     ◀── 멀티모달 입력
        ↓
MA1 멀티모달 임베딩 — 이미지 · 텍스트를 공통 벡터 공간으로
        ↓
MA3 오케스트레이터 에이전트 — 의도 분석 · 작업 분해 · 분배        ◀── 멀티에이전트 시작 (라우터 자리)
        ├──────────────────────────┬──────────────────────────┐
        ↓                          ↓                          ↓
MA4 검색 전문가               MA5 분석 · 코딩              MA6 보고서 작성
 - MA2 멀티모달 RAG            - 표 · 그래프 데이터 파싱      - sLLM / LLM 라우팅
 - 이미지 · 텍스트 청크 검색    - 코드 실행(계산 · 검증)       - 템플릿 맞춤 작성
 - 멀티모달 리랭킹 · 재검색     - 결과 차트                   - 답변 가공
        └──────────────────────────┼──────────────────────────┘
                                   ↓
                  MA7 품질 검증 · 교차 검증 (통과 / 수정 요청 / 반려)
                                   ↓
                  MA8 멀티모달 답변 (텍스트 + 차트 + 음성)           ◀── 멀티모달 출력
```

## 단계

<!-- 단계 표: scripts/gen_docs.py 가 레지스트리로 채웁니다. 이 표시 사이는 고치지 마세요. -->
| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| MA1 | [멀티모달 입력 · 임베딩](../stages/multi-agent/ma1-input/README.md) | 🟡 기초 있음 | 텍스트 · 이미지 · 음성 · 문서를 공통 벡터 공간에 놓아, 사진으로 매뉴얼을 찾는 식의 교차 검색을 한다 | [M 멀티모달](../stages/llm/m-multimodal/README.md) · [1 임베딩](../stages/llm/1-embedding/README.md) | [LLM 맵 · 멀티모달](../stages/llm/m-multimodal/multimodal.md) |
| MA2 | [멀티모달 RAG](../stages/multi-agent/ma2-rag/README.md) | 🟡 기초 있음 | 표 · 그래프 · 설계도를 글로 바꾸지 않고 이미지 청크 그대로 저장 · 검색하고, 멀티모달로 다시 순위를 매긴다 | [2 RAG](../stages/llm/2-rag/README.md) · [M 멀티모달](../stages/llm/m-multimodal/README.md) · [3 리랭킹](../stages/llm/3-rerank/README.md) | [LLM 연결 · 그림 근거 답변](../guides/llm.md) |
| MA3 | [오케스트레이터 에이전트](../stages/multi-agent/ma3-orchestrator/README.md) | ⬜ 예정 | 복잡한 요청을 작업으로 쪼개(Task Decomposition) 전문가 에이전트에게 나눠 주고 결과를 모은다 — 라우터 자리의 진화 | [6 라우팅](../stages/llm/6-routing/README.md) · [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | [LLM 맵 · 에이전트 실측](../stages/llm/8a-agent/agent.md) |
| MA4 | [검색 전문가 에이전트](../stages/multi-agent/ma4-retrieval-agent/README.md) | 🟡 기초 있음 | 사내 문서 · 이미지 · 웹 검색만 맡고, 결과가 부실하면 스스로 질의를 고쳐 다시 찾는다(Self-RAG) | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) · [4 검색 향상](../stages/llm/4-search-lab/README.md) · [2 RAG](../stages/llm/2-rag/README.md) | — |
| MA5 | [분석 · 코딩 에이전트](../stages/multi-agent/ma5-analysis-agent/README.md) | ⬜ 예정 | 검색된 표 · 수치를 파이썬 코드로 계산 · 검증하고 결과 차트를 만든다 | [8a 에이전틱 AI](../stages/llm/8a-agent/README.md) | — |
| MA6 | [보고서 작성 에이전트](../stages/multi-agent/ma6-report-agent/README.md) | ⬜ 예정 | 모은 근거 · 분석 결과로 정해진 형식의 답 · 보고서를 쓴다 — 쉬운 작성은 소형 모델, 어려운 작성은 큰 모델 | [6 라우팅](../stages/llm/6-routing/README.md) · [7a 지식 증류](../stages/llm/7a-distill/README.md) · [7b 양자화](../stages/llm/7b-quant/README.md) | [LLM 맵 · 소형 모델 실측](../stages/llm/7b-quant/quant.md) |
| MA7 | [품질 검증 에이전트](../stages/multi-agent/ma7-critic-agent/README.md) | 🟡 기초 있음 | 최종 답이 원문과 맞는지(환각) · 질문에 답하는지 · 보안 규정을 어기지 않는지 검사해 반려하거나 통과시킨다 | [2 RAG](../stages/llm/2-rag/README.md) · [8b 강화학습](../stages/llm/8b-rl/README.md) | [LLM 맵 · 답변 원칙과 검증](../stages/llm/2-rag/rag.md) |
| MA8 | [멀티모달 출력](../stages/multi-agent/ma8-output/README.md) | ⬜ 예정 | 텍스트 답에 더해 차트 · 이미지 · 음성으로 결과를 낸다 | [M 멀티모달](../stages/llm/m-multimodal/README.md) | — |
<!-- /단계 표 -->

## 단계별로 이미 있는 것과 새로 만들 것

| 단계 | 상태 | 이미 있는 것 (기반 단계) | 새로 만들 것 |
|---|---|---|---|
| [MA1 멀티모달 입력 · 임베딩](../stages/multi-agent/ma1-input/README.md) | 🟡 기초 있음 | [M 멀티모달](../stages/llm/m-multimodal/README.md): 이미지 · 영상 장면을 텍스트와 같은 공간에서 검색(한국어 질의는 EmbeddingGemma 2 가 CLIP 보다 크게 나음) | 이미지로 이미지 · 문서 찾기, 사진 + 질문 질의, 음성 입력(STT) |
| [MA2 멀티모달 RAG](../stages/multi-agent/ma2-rag/README.md) | 🟡 기초 있음 | 이미지 · 프레임 1장 = 청크 1개 색인 · 검색, 그림 근거를 비전 LLM(Gemma 4 + mmproj)에 첨부해 번호로 인용 | PDF 표 · 그림을 이미지 청크로, 멀티모달 리랭킹 |
| [MA3 오케스트레이터](../stages/multi-agent/ma3-orchestrator/README.md) | ⬜ 예정 | [6 라우팅](../stages/llm/6-routing/README.md)(규칙 · 확신도 · LLM · 학습 라우터), [8a 에이전트](../stages/llm/8a-agent/README.md)(ReAct · 도구) | 작업 계획(JSON) · 실행기, 단일 vs 멀티에이전트 비교 |
| [MA4 검색 전문가](../stages/multi-agent/ma4-retrieval-agent/README.md) | 🟡 기초 있음 | 에이전트 search · read · lookup 도구, [4 검색 향상](../stages/llm/4-search-lab/README.md), 하이브리드 검색 | 충분성 판단 · 재검색 루프(Self-RAG), 이미지 · 웹 검색 |
| [MA5 분석 · 코딩](../stages/multi-agent/ma5-analysis-agent/README.md) | ⬜ 예정 | 에이전트 calc(산술식만, 코드 실행 없음) | 격리된 코드 실행기, 표 파싱 · 차트 |
| [MA6 보고서 작성](../stages/multi-agent/ma6-report-agent/README.md) | ⬜ 예정 | 라우팅의 경로별 답변 모델, [7b 양자화](../stages/llm/7b-quant/README.md) · [7a 증류](../stages/llm/7a-distill/README.md) 소형 모델 실측, 답변 원칙 | 출력 템플릿, 작성 난이도별 모델 라우팅 |
| [MA7 품질 검증](../stages/multi-agent/ma7-critic-agent/README.md) | 🟡 기초 있음 | 답변 검증(근거 일치 · 질문 관련성 · 조문 · 판례 번호 검사), 사람 판정 보정, [8b 강화학습](../stages/llm/8b-rl/README.md) 보상 · Best-of-N | 반려 · 재작성 루프, 보안 규정 검사 |
| [MA8 멀티모달 출력](../stages/multi-agent/ma8-output/README.md) | ⬜ 예정 | 그림 근거를 읽고 글로 답하기(비전 입력) | 차트 출력, 음성 안내(TTS) |

## 기반 실측에서 가져온 설계 원칙

이 맵을 만들 때 LLM 맵에서 잰 결과를 그대로 반영합니다.

1. **단계를 늘릴수록 단계마다 검증한다.** 작은 로컬 모델(Gemma 4 E4B)의 에이전트 답은 판례 질문에서 문장 근거율 50% 로 RAG(91%)보다 근거 밖 문장이 많았습니다([에이전트 실측](../stages/llm/8a-agent/agent.md#실측)). 에이전트를 여럿 이으면 앞 단계의 실수가 뒤로 전달됩니다.
2. **정할 수 있는 것은 규칙으로, 나머지만 LLM 에.** 질문에 조문 번호가 있으면 번호 조회를 LLM 판단 전에 먼저 하도록 바꾸자 조문 번호 질문의 정답 근거 인용이 75% → 100% 가 됐습니다. 오케스트레이터의 작업 분배도 규칙으로 정할 수 있는 부분(번호 → 조회, 사진 → 멀티모달 검색)은 규칙으로 둡니다.
3. **LLM 검증만 믿지 않는다.** 사람 판정 28개에서 작은 LLM 판정은 모두 '근거 있음'이었습니다([답변 원칙과 검증](../stages/llm/2-rag/rag.md#답변-원칙-질문과-관련된-근거로만)). 검증 에이전트는 사람 판정으로 보정한 점수(근거 일치 · 질문 관련성)를 함께 씁니다.
4. **작성 모델은 난이도로 나눈다.** 소형 모델 E2B 는 E4B 보다 지연 −21% 대신 품질 −13(유의)이었습니다([소형 모델 실측](../stages/llm/7b-quant/quant.md#실측)). 짧은 정형 작성만 sLLM 으로 보냅니다.
5. **단순한 질문은 그대로 RAG 한 번.** 계획 · 분배 비용이 답변보다 클 수 있습니다. 단일 vs 멀티에이전트를 같은 평가 세트로 비교해(품질 · 시간 · LLM 호출 수) 언제 멀티에이전트를 쓸지 정합니다.
6. **코드 실행은 격리가 먼저.** 지금의 calc 도구는 LLM 이 만든 문자열을 실행하지 않는 산술 계산기입니다. 분석 에이전트의 코드 실행기는 시간 · 메모리 · 네트워크 제한과 허용 라이브러리를 정한 격리 환경 없이는 켜지 않습니다.

## 두 개념이 합쳐지면 — 예시

**AS 문의**: 고객이 세탁기 오류 화면 사진을 올림(멀티모달 입력) → 오케스트레이터가 작업을 나눔 → 검색 에이전트가 사진으로 비슷한 오류 사례 · 매뉴얼 쪽을 찾음 → 분석 에이전트가 오류 코드 표에서 원인 · 조치 순서를 확인 → 작성 에이전트가 안내문을 씀 → 검증 에이전트가 매뉴얼과 맞는지 · 질문에 답하는지 확인 → 단계별 그림과 음성 안내로 답(멀티모달 출력).

## 진행 순서 (계획)

1. **MA7 반려 · 재작성 루프** — 이미 있는 검증 점수로 가장 빨리 효과를 볼 수 있는 단계.
2. **MA4 재검색 루프** — 근거 검색률로 바로 잴 수 있음.
3. **MA3 오케스트레이터 v1** — 규칙 우선 분배 + LLM 계획, 단일 vs 멀티에이전트 실측.
4. **MA1 · MA2 이미지 질의 · PDF 그림 청크**, **MA5 격리 실행기**, **MA6 템플릿**, **MA8 차트 · 음성** 순.

---

다른 맵: [문서 색인의 맵 목록](../README.md#맵)
