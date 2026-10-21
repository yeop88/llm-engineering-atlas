<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 문서 처리 (Document Intelligence) 맵

수집 → 파싱(HWP · PDF · OCR) → 레이아웃 · 표 · 그림 → 정제 · 중복 · 버전 → 청킹 → 메타데이터 · 증분 갱신 → 품질 점검 — 자료를 제대로 읽는 흐름

RAG 의 품질은 검색 모델보다 먼저 '자료를 제대로 읽었는가'에서 정해집니다. 법률 재측정의 문제 상당수가 여기서 났습니다 — 근거 문장이 청크 경계에서 잘리고, 짧은 조문 청크가 35% 였고, 법령 표의 행 반복이 섞였습니다. 이 맵은 원본이 들어와 색인되기 전까지의 처리와 그 점검을 다룹니다.

앱의 **맵 → 문서 처리 (Document Intelligence) 맵**(`/maps/docintel`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[수집 · 연결] → [파싱 (HWP · PDF · DOCX · OCR)] → [레이아웃 · 표 · 그림 추출]
                                      ↓
[정제 · 중복 · 버전] → [청킹] → [메타데이터 · 증분 갱신]
                                      ↓
                         [데이터 품질 점검]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| D1 | [수집 · 연결](../stages/docintel/d1-ingest/README.md) | ✅ 구현됨 | 파일 업로드 · 공개 데이터 · 사내 시스템에서 원본을 가져오고 출처를 남긴다 | [2 RAG](../stages/llm/2-rag/README.md) | [수집 · 메타데이터 · 증분 갱신](../stages/docintel/d1-ingest/ingest.md) |
| D2 | [파싱 (HWP · PDF · DOCX · OCR)](../stages/docintel/d2-parse/README.md) | ✅ 구현됨 | 형식마다 맞는 파서로 글 · 구조를 뽑고, 스캔 문서는 OCR 로 읽는다 | [2 RAG](../stages/llm/2-rag/README.md) | [파싱 점검 · OCR · 표 · 그림](../stages/docintel/d2-parse/parsing.md) |
| D3 | [레이아웃 · 표 · 그림 추출](../stages/docintel/d3-layout/README.md) | ✅ 구현됨 | 제목 · 단락 · 표 · 그림 영역을 나눠, 표는 구조로 · 그림은 이미지 청크로 남긴다 | [M 멀티모달](../stages/llm/m-multimodal/README.md) · [MA2 멀티모달 RAG](../stages/multi-agent/ma2-rag/README.md) | [파싱 점검 · OCR · 표 · 그림](../stages/docintel/d2-parse/parsing.md) |
| D4 | [정제 · 중복 · 버전](../stages/docintel/d4-clean/README.md) | ✅ 구현됨 | 머리말 · 반복 행 같은 잡음을 걷고, 거의 같은 문서 · 개정판을 정리한다 | [2 RAG](../stages/llm/2-rag/README.md) · [A 의미 응용](../stages/llm/a-apps/README.md) | [정제 · 청크 품질 · 근거 보존](../stages/docintel/d4-clean/quality.md) |
| D5 | [청킹](../stages/docintel/d5-chunk/README.md) | ✅ 구현됨 | 문서를 검색 단위로 자르되 근거 문장이 경계에서 잘리지 않게 한다 | [2 RAG](../stages/llm/2-rag/README.md) | [정제 · 청크 품질 · 근거 보존](../stages/docintel/d4-clean/quality.md) |
| D6 | [메타데이터 · 증분 갱신](../stages/docintel/d6-meta/README.md) | ✅ 구현됨 | 문서 날짜 · 종류 · 권한 메타데이터를 붙이고, 바뀐 문서만 다시 색인한다 | [2 RAG](../stages/llm/2-rag/README.md) | [수집 · 메타데이터 · 증분 갱신](../stages/docintel/d1-ingest/ingest.md) |
| D7 | [데이터 품질 점검](../stages/docintel/d7-quality/README.md) | ✅ 구현됨 | 처리 단계별 건수 · 길이 분포 · 근거 보존을 점검하고 처리 기록을 남긴다 | [2 RAG](../stages/llm/2-rag/README.md) · [E1 평가 세트](../stages/evalops/e1-sets/README.md) | [정제 · 청크 품질 · 근거 보존](../stages/docintel/d4-clean/quality.md) |

## 설계 원칙

- 통계보다 실제 텍스트를 연다 — 법령 반복 행은 건수 통계로는 보이지 않았다
- 근거가 청크에 온전히 들어가는지 잰다 — 생성 근거의 6% 가 원문과 달랐고 일부는 청크 경계 때문
- 짧은 청크는 합친다 — merge_below 200 으로 청크 −42%, 품질 동일
- 처리 기록은 단계별 건수와 함께 남긴다(data-processing.md)

## 예시

스캔 PDF 규정집: 텍스트가 없으면 OCR → 표는 이미지 청크와 표 구조를 함께 → 조항 단위 청킹 → 개정일 메타데이터 → 개정판이 오면 바뀐 조항만 다시 색인.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md)
