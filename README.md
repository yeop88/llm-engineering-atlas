# LLM Engineering Atlas

**Global LLM system engineering lab · Korean-first** — LLM 시스템을 **맵 18개 · 단계 132개**로 펼쳐 놓고, 단계마다 직접 실험 · 측정하며 부분 · 전체로 이어 보는 웹 실험실입니다. 다국어로 동작하며, 한국어(HWP 문서 · 형태소 검색 · 법령 구조 등)에 특화되어 있습니다.

```
                          ┌──────── LLM 시스템 엔지니어링 맵 (본선 · 12단계 모두 구현) ────────┐
[데이터 임베딩] → [RAG 검색] → [리랭킹] → [라우팅] → 쉬운 질문: [지식 증류 · 양자화된 소형 모델]
                                                      → 어려운 질문: [파인튜닝 · 강화학습된 에이전트 LLM]
                          └────────────────────────────┬──────────────────────────────────────┘
                                 이미 있는 단계를 '기반 단계'로 삼아 다른 관점의 맵을 짓는다
   평가 · 관측 · 보안 · 문서 처리 · 서빙 · AS 상담 · 지식 그래프 · 멀티에이전트 · 음성 · 규제 대응 …
```

- **LLM 시스템 엔지니어링 맵**이 본선입니다. 임베딩부터 에이전트 · 강화학습까지 12단계를 모두 구현했고, 단계마다 화면 · API · 실측 기록이 있습니다.
- **다른 17개 맵**은 같은 시스템을 다른 관점(운영 · 보안 · 업무 시나리오 · 새 기술)으로 본 것입니다. 단계마다 이미 있는 기능(기반 단계)을 연결해 🟡 **기초 있음**으로, 아직 없는 것은 ⬜ **예정**으로 표시하고, 차례로 구현합니다.
- 각 단계를 **따로 실험하고 숫자로 검증**합니다. 평가 세트 · 부트스트랩 신뢰구간 · 짝지은 비교로 "정말 좋아졌는가"를 판정하고, 실측 결과(잘된 것과 안 된 것, 정정 기록까지)를 문서에 남깁니다.

(이전 이름: Embedding Lab — 오픈소스 임베딩 모델을 관리 · 테스트 · 벤치마크하는 도구에서 출발했습니다.)

## 맵

<!-- 맵 표: scripts/gen_docs.py 가 레지스트리로 채웁니다. 이 표시 사이는 고치지 마세요. -->
| 맵 | 무엇을 | 단계 | ✅ | 🟡 | ⬜ | 화면 · 개요 |
|---|---|---|---|---|---|---|
| **LLM 시스템 엔지니어링** | 문서 지식을 싸고 빠르고 정확하게 서비스하는 흐름 | 12 | 12 | — | — | `/maps/llm` · [개요](docs/maps/llm.md) |
| **지식 그래프 · GraphRAG** | 개념과 관계를 구조로 저장해 다단계 · 집계 · 전체 요약 질문에 답하는 흐름 | 8 | 8 | — | — | `/maps/knowledge-graph` · [개요](docs/maps/knowledge-graph.md) |
| **멀티에이전트 · 멀티모달** | 멀티모달 입력 · 검색 → 오케스트레이터가 전문가 에이전트(검색 · 분석 · 작성 · 검증)에게 분배 → 교차 검증 → 텍스트 · 차트 · 음성 출력 | 8 | 8 | — | — | `/maps/multi-agent` · [개요](docs/maps/multi-agent.md) |
| **평가 · 관측 (LLMOps)** | 서비스가 지금 잘 되고 있는지 숫자로 아는 흐름 | 8 | 8 | — | — | `/maps/evalops` · [개요](docs/maps/evalops.md) |
| **보안 · 가드레일 · 거버넌스** | 써도 되는 답인지 확인하는 흐름 | 7 | 7 | — | — | `/maps/guardrails` · [개요](docs/maps/guardrails.md) |
| **문서 처리 (Document Intelligence)** | 자료를 제대로 읽는 흐름 | 7 | 7 | — | — | `/maps/docintel` · [개요](docs/maps/docintel.md) |
| **서빙 · 추론 최적화 · 비용** | 싸고 빠르게 돌리는 흐름 | 7 | — | 5 | 2 | `/maps/serving` · [개요](docs/maps/serving.md) |
| **대화 · 메모리** | 한 번이 아니라 이어지는 상담을 다루는 흐름 | 6 | 6 | — | — | `/maps/conversation` · [개요](docs/maps/conversation.md) |
| **서비스 시나리오: 고객 AS 상담** | 기술 맵들을 실제 업무로 묶은 흐름 | 8 | 8 | — | — | `/maps/as-service` · [개요](docs/maps/as-service.md) |
| **후학습 (Post-training)** | 우리 데이터로 LLM 자체를 고치는 흐름 | 7 | — | 3 | 4 | `/maps/posttrain` · [개요](docs/maps/posttrain.md) |
| **데이터 플라이휠** | 평가 · 후학습 · 서빙 · 가드레일을 하나의 순환으로 | 7 | — | 4 | 3 | `/maps/flywheel` · [개요](docs/maps/flywheel.md) |
| **엔터프라이즈 AI 플랫폼 아키텍처** | 맵들을 실제 운영 시스템으로 묶는 흐름 | 7 | — | 3 | 4 | `/maps/platform` · [개요](docs/maps/platform.md) |
| **에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)** | 신뢰 경계를 넘나드는 에이전트 연결 | 6 | 6 | — | — | `/maps/interop` · [개요](docs/maps/interop.md) |
| **실시간 음성 상담** | 전화 AS 상담 | 7 | — | — | 7 | `/maps/voice` · [개요](docs/maps/voice.md) |
| **규제 대응 · 컴플라이언스** | 법 조항을 시스템 요구로 | 8 | 8 | — | — | `/maps/compliance` · [개요](docs/maps/compliance.md) |
| **장기 실행 에이전트 · 업무 자동화** | 며칠짜리 업무를 맡기는 흐름 | 7 | 7 | — | — | `/maps/longrun` · [개요](docs/maps/longrun.md) |
| **강화학습 기반 에이전트 학습 (RLVR)** | 정답을 확인할 수 있는 과제로 에이전트를 학습 | 6 | — | 3 | 3 | `/maps/rlvr` · [개요](docs/maps/rlvr.md) |
| **온디바이스 · 엣지** | 서버 없이 기기에서 돌리는 흐름 | 6 | — | 3 | 3 | `/maps/edge` · [개요](docs/maps/edge.md) |
| **합계 18개** | | 132 | 85 | 21 | 26 | `/maps` |
<!-- /맵 표 -->

✅ 구현됨 · 🟡 기초 있음(기능은 다른 맵에 있고, 이 맵의 관점으로 묶은 화면 · 측정은 아직) · ⬜ 예정 — 맵 · 단계의 정의와 상태는 `app/stages/registry/` 한 곳에서 관리하고, 이 표와 문서가 거기서 만들어집니다.

## LLM 시스템 엔지니어링 맵 — 단계별 기능

| 단계 | 이 앱에서 할 수 있는 것 |
|---|---|
| **1 데이터 임베딩** | 2026-10 기준 임베딩 모델 37개 · 리랭커 11개 카탈로그(EmbeddingGemma 2 포함), Hub 검색 · 다운로드 · LRU 로드, **새 모델 후보**(Hub 인기 급상승 중 카탈로그에 없는 것), **호환성 점검**(라이브러리를 올린 뒤 내려받은 모델이 그대로 도는지), 플레이그라운드(검색 비교 · 유사도 행렬 · 임베딩 지도 · Matryoshka), 벤치마크(내장 · 공개 한국어 6종 · 내 데이터셋, 95% 신뢰구간 · 1위 대비 유의성, 차트) |
| **2 RAG 검색** | HWP · HWPX · PDF · DOCX 등 업로드, **공개 자료 가져오기**(근로 · 주택임대차 법령과 판례), 청킹 5종(법령 · 판결문 구조 포함) · 짧은 청크 합치기, 벡터 인덱스(Qdrant 기본 · pgvector · MariaDB, 작은 인덱스는 정확 검색), 한국어 형태소 BM25 · 하이브리드(RRF), 평가 세트(LLM 질문 7유형 — 조건 · 긴 상황 · 여러 문서 · 답 없음 포함, 직접 입력) · 조합 평가, 근거 번호를 인용하는 LLM 답변(스트리밍 · 근거 압축 · 그림 근거 첨부), 문장별 **근거 일치 · 질문 관련성** 검증과 사람 판정으로 기준을 고르는 **검증 보정**, **조문 · 판례 번호 조회와 인용 번호 검사**, 답변 일괄 평가 |
| **3 리랭킹** | 크로스 인코더 11종 · LLM 목록형 리랭커, 1단계 순위와의 융합, 리랭커 × 후보 수 × 융합 품질-지연 평가 |
| **4 검색 향상** | 질의 재작성 · HyDE · 다중 질의(원 질의와 RRF 융합, LLM 변형 캐시), 검색 · 평가 · 답변 어디서든 적용, 기법별 나란히 비교 · 평가 세트 비교 |
| **5 파인튜닝** | 컬렉션 지문으로 학습 쌍 생성(LLM 질문 · ICT, 평가 근거 누수 방지), 대조 학습, 카탈로그 자동 등록, 학습 전후 짝지은 비교, 실행 기록(모델 카드) |
| **6 라우팅** | 규칙 · 검색 확신도 · LLM 판단 · **학습 라우터**로 쉬운 질문은 빠른 경로, 어려운 질문은 전체 경로, 평가 세트로 항상 빠른 · 항상 전체 · 오라클과 비용-품질 비교 |
| **7a 지식 증류** | 임베딩 증류(교사 = 큰 임베딩 · 리랭커, MarginMSE, 격차 회복률 · 속도), LLM 증류 데이터(검증 통과한 교사 답 JSONL) |
| **7b 양자화** | 임베딩 벡터 int8 · binary(+재점수) 정확도 · 메모리 비교, LLM GGUF 비트 수(Q8_0 · QAT Q4_0 · Q2_K)별 답변 품질 · 속도, 모델별 LLM 서버 주소 |
| **8a 에이전틱 AI** | 검색 · 읽기 · 계산 · 법률 번호 조회 도구를 여러 번 쓰는 다단계 RAG(단계 기록 · 근거 검증), 연결 실행 · 라우팅의 어려운 경로 답변 방식 |
| **8b 강화학습** | 보상 함수, Best-of-N, 선호 쌍(자동 · 사람) 수집, DPO 데이터 내보내기 |
| **M 멀티모달** | 텍스트로 이미지 검색(EmbeddingGemma 2 · Qwen3-VL-Embedding · Jina v5 Omni · CLIP), 이미지 · 영상을 컬렉션에 올려 장면 검색(영상 프레임 추출 · 같은 장면 제외, 썸네일 · 장면 시각으로 이동) |
| **A 의미 응용** | 추천(MMR) · 분류(제로샷 · 학습, 분류기 저장/예측 API) · 군집 · 중복/표절 · 이상/신종 탐지 · 키워드/요약 |
| **연결 실행** | 맵 화면(`/maps/llm`)에서 단계를 켜고 끄며 한 질문을 서비스 순서대로 처리(단계별 상태 · 시간, 미구현 단계는 기본 동작), 평가 세트로 부분 · 전체 연결 비교 |
| **공통 · 운영** | LLM 연결(로컬 llama.cpp · OpenAI 호환 · Claude API, 기본 Gemma 4 E4B), 실행 이력 · 추세 · 내보내기, 대시보드, 백그라운드 작업 기록(재시작해도 남음), 선택형 접근 토큰(`API_TOKEN`), Docker |

## 실측으로 확인한 것

모든 수치는 이 PC(CPU · 내장 GPU)에서 잰 것이고, 자료 · 설정 · 신뢰구간 · 한계는 링크한 단계 문서에 있습니다.

| 질문 | 결과 | 문서 |
|---|---|---|
| 법률 자료는 어떤 검색이 맞나 | 판례 중심 세트는 하이브리드 nDCG 74.1, 법령 세트는 의미 검색 88.0 — 자료 종류마다 다르다 | [2 RAG](docs/stages/llm/2-rag/rag.md) |
| 짧은 청크를 합치면 | 청크 −42%(2,762 → 1,613), 품질 차이 없음 | [2 RAG](docs/stages/llm/2-rag/rag.md) |
| 리랭커를 붙이면 좋아지나 | 리랭커 단독은 −4.6(불확실), 1단계 순위와 융합해야 +1.0 — CPU 에서는 질문당 12~48초 | [3 리랭킹](docs/stages/llm/3-rerank/rerank.md) |
| 라우팅으로 아낄 수 있나 | 학습 라우터가 항상 전체 경로와 같은 품질로 지연 −25%(73.0 → 55.1초) — 다만 '어려움' 라벨 5개로 낸 결과라 기준값에 민감 | [6 라우팅](docs/stages/llm/6-routing/routing.md) |
| 소형 · 저비트 모델은 | QAT Q4_0 이 Q8_0 과 같은 품질로 가장 빠름, 소형 E2B 는 지연 −21% 대신 품질 −13(유의) | [7b 양자화](docs/stages/llm/7b-quant/quant.md) |
| 에이전트가 RAG 보다 나은가 | 조문 번호 질문에서 번호 조회를 LLM 판단 전에 먼저 하게 하자 정답 근거 인용 75% → 100% | [8a 에이전틱 AI](docs/stages/llm/8a-agent/agent.md) |
| 근거를 줄이면 빨라지나 | 근거 압축은 지연 −19% 대신 품질 −10(정답 문장을 버림). A/B 재생 120문항에서는 −19초(유의) · 근거 일치는 차이 없음(+0.017, 불확실) | [2 RAG](docs/stages/llm/2-rag/rag.md) · [E7 A/B](docs/stages/evalops/e7-ab/ab.md) |
| 방어를 켜면 얼마나 막나 | 공격 31개 방어율 off 58% → mask(개인정보 가림 · 근거 격리) 87% → enforce 100%, 정상 질문 6개는 세 모드 모두 답함(처음엔 enforce 가 지시 섞인 청크를 통째로 빼 정상 질문 절반을 거절 — 문장 단위로 고침) | [G1 · G7 가드레일](docs/stages/guardrails/g1-injection/guards.md) |
| 권한은 어디서 지키나 | 검색 전에 거르면 권한 없는 문서가 근거로 나올 질문 9/17 → 0, 방어 모드와 무관 | [G3 권한](docs/stages/guardrails/g3-acl/access.md) |
| 설정을 바꾸면 회귀를 잡나 | 하이브리드 → BM25 만: 두 세트 모두 유의한 하락 경보(nDCG −0.12 · −0.09), 같은 설정은 차이 0 | [E2 회귀](docs/stages/evalops/e1-sets/regression.md) |
| 바뀐 문서만 다시 색인하면 | 문서 1개 변경: 증분 42초 vs 전체 재구축 30분(1,613청크) | [D6 증분 갱신](docs/stages/docintel/d1-ingest/ingest.md) |
| 스캔 PDF · 표는 | 비전 LLM OCR 본문 99.4% · 표 셀 100%, pdfplumber 표 추출 셀 36/36 (만든 PDF) | [D2 · D3 파싱](docs/stages/docintel/d2-parse/parsing.md) |
| AS 상담에 제품 범위가 필요한가 | 끄면 맞는 매뉴얼은 잡지만 다른 모델 매뉴얼이 79% 답의 근거에 섞이고 5.6초 느려짐 | [AS 상담 흐름](docs/stages/as-service/as1-intake/console.md) |
| 후속 질문은 어떻게 검색하나 | '그럼 단시간 근로자도 받나요?' 같은 후속 질문 24개: 그대로 Hit@1 54% → LLM 으로 풀어 쓰기 79%(법률 33 → 67%), 제품 매뉴얼은 규칙(기억한 제품 덧붙임)만으로 92% | [대화 · 메모리](docs/stages/conversation/c1-rewrite/conversation.md) |
| 지식 그래프로 검색이 나아지나 | 법률 자료(판례 164)에서 벡터 결과에 그래프 이웃을 붙이면 hit 98.2 → 97.2(k=10) · 93.6 → 88.5(k=5) — 나아지지 않음. 관계를 묻는 질문은 Text2Cypher 가 맞힘(한 단계 조회 100%, 역량 질문 정확 일치 40 → 53%) | [K5 · GraphRAG](docs/stages/knowledge-graph/k5-graph-db/graphrag.md) |
| Neo4j 와 FalkorDB 는 | 같은 그래프 · 기대 Cypher 15개 결과 모두 같음, FalkorDB 가 메모리 77 vs 810MiB · 지연 5 vs 15ms. Text2Cypher 정확도는 엔진이 아니라 LLM 이 가름(방언 두 가지는 변환으로 해결) | [K5 · GraphRAG](docs/stages/knowledge-graph/k5-graph-db/graphrag.md#k6-cypher-엔진-비교--neo4j-526-vs-falkordb-422) |
| 규제 자료는 어디서 받나 | 법률 데이터셋은 '제N조의M' 가지번호를 버려 개인정보 보호법 조항이 126 → 76개 — 국가법령정보 API 의 시행일별 판으로. 2026-01-22 판을 현행과 비교해 개정 조항을 개정 표시 기준 16/16 · 23/23 · 5/5 감지, 바뀐 조항 → 영향받는 통제 · 기능 | [규제 대응](docs/stages/compliance/rc1-scope/compliance.md) |
| 의무로 근거 조항을 찾나 | '보관 기간이 끝난 상담 기록은 지워야 하나요?' 같은 의무 질문 22개: 혼합 검색 hit@10 100% · hit@1 77% — 1위는 비슷한 조항이 앞서 적용 판단은 규칙으로 | [규제 대응](docs/stages/compliance/rc1-scope/compliance.md#rc1-의무--조항-검색) |
| 통제는 실제로 동작하나 | 통제 15개 감사 — 처음엔 실패 5(AI 응답 고지 기록 0 · 처리 근거 미등록 · 등급 · 영향 평가 없음 · 요청 기록 보관 기한 없음), 남은 빈틈은 보관 기한 · 유출 통지 절차 · 질문 원문의 사람별 삭제 | [규제 대응](docs/stages/compliance/rc1-scope/compliance.md#rc8-통제-감사--처음-상태--흐름을-거친-뒤) |
| AS 의도는 무엇으로 나누나 | 라벨 48개에서는 임베딩 제로샷 95.8% > 학습 분류기 85.4% — 라벨이 쌓이기 전엔 제로샷 | [AS2 분류](docs/stages/as-service/as2-triage/eval.md) |

## 기술 스택 (2026-10 최신 안정 버전)

Python 3.14.6 · FastAPI 0.143.3 · Uvicorn 0.54.0 · Starlette 1.8 · Pydantic 2.14 · SQLAlchemy 2.1.5 · Alembic 1.20 · sentence-transformers 6.1.0 (+ train: datasets 5.1 · accelerate 1.15) · transformers 5.20.1 · PyTorch 2.14.1 (CPU / CUDA 12.6·13.0 / ROCm 7.2) · huggingface-hub 1.33.0 · pyarrow 26 · httpx 0.28 · Qdrant 1.19 (qdrant-client 1.19) · pgvector 0.8.7 (PostgreSQL 18) · MariaDB 13.0 · Kiwi 0.24 (한국어 형태소) · PyAV 19 (영상 프레임) · pdfplumber 0.11 · pypdfium2 5 (PDF 표 · 쪽 그림) · Neo4j 5.26 LTS (neo4j 드라이버 6.4, 선택) · networkx 3.7 (커뮤니티 탐지) · Jinja2 · Chart.js 4.5.1 (CDN) · pytest 9.1 · ruff 0.17 · uv 0.12

로컬 LLM(선택): llama.cpp `llama-server` b11669(v0.7.0, Vulkan) + Gemma 4 E4B QAT q4_0(비전 프로젝터 `--mmproj` 를 붙이면 OCR · AS 사진 진단도) — [docs/guides/llm.md](docs/guides/llm.md)

> huggingface-hub 2.x가 나와 있지만 sentence-transformers 6.1이 `<2.0`을 요구하므로 1.x 최신을 사용합니다.

## 빠른 시작

시스템에 Python이 없어도 됩니다. [uv](https://docs.astral.sh/uv/)가 Python 3.14를 자동으로 받아 가상환경을 만듭니다.

```powershell
# 1) uv 설치 (없다면)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2) 의존성 설치 — 가속기에 맞춰 하나 선택 (docs/guides/gpu.md)
uv sync --extra cpu        # CPU 전용
# uv sync --extra cu130    # NVIDIA GPU (CUDA 13.0, 최신 드라이버)
# uv sync --extra cu126    # NVIDIA GPU (CUDA 12.6)
# uv sync --extra rocm     # AMD GPU (Linux 전용)

# 3) (선택) 설정
copy .env.example .env      # gated 모델용 HF_TOKEN, 접근 토큰 API_TOKEN, LLM 주소 등

# 4) (선택) 벡터 DB 서버 — 없어도 Qdrant 로컬 파일 모드로 동작
docker compose up -d                                        # Qdrant
docker compose --profile pgvector --profile mariadb up -d   # + pgvector, MariaDB
docker compose --profile neo4j up -d                        # + Neo4j (지식 그래프 Cypher, 선택)
docker compose --profile falkordb up -d                     # + FalkorDB (두 번째 Cypher 엔진, 선택)

# 5) 실행 (DB 마이그레이션은 시작할 때 자동 적용)
uv run uvicorn app.main:app --port 8000
```

브라우저에서 http://127.0.0.1:8000 을 엽니다. API 문서는 http://127.0.0.1:8000/docs 에 있습니다.

- **로컬 LLM**(답변 생성 · 평가 질문 생성 · 질의 재작성에 필요): `llama-server -m gemma-4-E4B_q4_0-it.gguf --port 8081 -c 16384 -ngl 99 --alias gemma-4-e4b` 처럼 띄우고 `.env` 의 `OPENAI_BASE_URL=http://127.0.0.1:8081/v1` — 자세히는 [LLM 연결](docs/guides/llm.md).
- **Docker 로 앱까지**: `docker compose --profile app up -d --build` (GPU 는 `TORCH_EXTRA=cu130`) — [배포 · 운영](docs/guides/deploy.md).
- Windows 에서 `uv run uvicorn` 이 '애플리케이션 제어 정책' 오류로 막히면 `uv run python -m uvicorn …` 으로 — [문제 해결](docs/guides/troubleshooting.md).

### 화면 구성

- **왼쪽 사이드바**: 대시보드 · 실험(LLM 시스템 맵의 단계 순서) · 운영 · 서비스(문서 처리 · 보안 · 가드레일 · 평가 · 관측 · 고객 AS 상담) · 맵 · 기록과 설정. 좁은 화면에서는 ☰ 로 엽니다.
- **위쪽 바**: 현재 위치(예: `2 RAG › 답변 생성`), **ⓘ 단계 원리**(그 단계의 원리 · 왜 · 어떻게), **⏳ 작업**(다른 화면에서도 백그라운드 작업 진행 · 취소, 끝나면 알림), **Ctrl K**(화면 · 단계 · 맵 · 컬렉션 이름으로 바로 이동), **◐**(테마: 시스템 · 밝게 · 어둡게).
- **작업 맥락 줄**: 컬렉션 · 인덱스 · 평가 세트 · LLM 을 한 번 고르면 모든 화면이 그 값으로 시작합니다. 주소에도 담겨(`?col=3&idx=11`) 새로 고침 · 링크 공유 후에도 같은 설정으로 열립니다.
- **맵**: 사이드바의 **모든 맵**(`/maps`)에서 18개 맵을 상태와 함께 보고, 맵 화면에서 흐름 · 단계 · 기반 단계를 따라갑니다.
- **주소 규칙**: 화면이 여럿인 단계는 `/<단계>/<화면>`(예: `/rag/collections`, `/embedding/models`), 하나인 단계는 `/<단계>`(예: `/routing`), 맵은 `/maps/<맵>`, 단계 소개는 `/stages/<단계>`, 설정은 `/settings/llm`. 0.x 의 예전 주소는 새 주소로 넘어갑니다.
- **대시보드**의 '다음에 할 일'이 아래 순서를 지금 상태로 체크해 줍니다.

### 처음 써보기 (흐름도 순서)

1. **1 임베딩 → 모델**에서 `EmbeddingGemma 2` 를 받아 로드하고, **플레이그라운드**에서 다른 모델과 검색 결과를 비교합니다. **벤치마크**에서 공개 한국어 벤치마크를 가져와 신뢰구간과 함께 평가합니다.
2. **2 RAG → 컬렉션**에서 HWP · PDF 문서를 올리거나 공개 자료(법령 · 판례)를 가져오고, 청크 세트 → 벡터 인덱스 → 검색 비교 → **⑤ 평가** 탭(평가 세트 · 조합 평가) 순서로 진행합니다.
3. (선택) 로컬 LLM 을 켜고 **기록 · 설정 → LLM 연결**에서 확인한 뒤 **2 RAG → 답변 생성**에서 근거를 인용한 답변과 문장별 검증을 봅니다.
4. **4 검색 향상**에서 구어체 질문을 넣어 질의 재작성 · HyDE · 다중 질의가 결과를 어떻게 바꾸는지 보고, 평가 세트로 효과를 잽니다.
5. **5 파인튜닝**에서 임베딩 모델을 컬렉션에 맞게 학습하고 전후를 비교합니다.
6. **맵 → LLM 시스템 엔지니어링 맵**(`/maps/llm`) 아래 **연결 실행**에서 단계들을 이어 붙여 한 질문을 처리하고, 평가 세트로 `검색만` · `검색 → 답변` · `전체 연결`을 비교합니다.
7. **운영 · 서비스 → 대화 · 메모리 → 대화 상담**에서 'WM-200 세탁기에 E4 가 떠요' → '필터는 어디 있어요?'처럼 이어 물어, 후속 질문을 어떻게 풀어 쓰고 무엇을 기억하는지 봅니다.
8. **운영 · 서비스 → 지식 그래프 · GraphRAG → 그래프 구축**에서 법률 컬렉션으로 그래프를 만들고, **그래프 탐색 · Cypher**에서 '근로기준법 제23조를 인용한 판례는?'을 Cypher 로, **GraphRAG**에서 같은 조문을 인용한 판례로 근거를 넓혀 봅니다.
9. **운영 · 서비스 → 규제 대응 · 컴플라이언스 → 적용 규제 · 위험 등급**에서 규제 자료(인공지능 기본법 · 개인정보 보호법)를 가져오고 기능별 적용 조항을 본 뒤, **조항-통제 매핑 · 개정 감시**에서 현행 판과 비교해 바뀐 조항이 어느 통제 · 기능에 닿는지, **영향 평가 · 통제 감사**에서 통제가 실제로 동작했는지 봅니다(`.env` 에 `LAW_API_OC`).
10. **운영 · 서비스 → 고객 AS 상담 → 상담 창**에서 예시 자료를 준비하고 오류 코드 · 사진으로 문의해 분류 · 답변 · 검증 · 티켓 흐름을 봅니다. 답변 화면 · 상담에서 남은 요청 기록은 **평가 · 관측 → 요청 기록 · 비용**, 방어는 **보안 · 가드레일 → 레드팀 시험**에서 확인합니다.
11. **모든 맵**에서 다른 관점의 맵을 열어, 각 단계가 어떤 기반 단계(이미 있는 기능)로 이어지는지 따라갑니다.

## 문서

전체 색인은 **[docs/README.md](docs/README.md)** 입니다. 문서는 **맵 → 단계** 순서로, 모든 맵이 같은 구조를 따릅니다.

- 맵 개요 `docs/maps/<맵>.md` — 위 [맵](#맵) 표의 '개요' 링크
- 단계 문서 `docs/stages/<맵>/<번호>-<이름>/` — 단계 README(원리 · 왜 · 어떻게 · 화면 · 할 일 · 기반 단계)와 상세 · 실측 기록. 예: [2 RAG](docs/stages/llm/2-rag/README.md)([상세](docs/stages/llm/2-rag/rag.md)) · [6 라우팅](docs/stages/llm/6-routing/README.md)([상세](docs/stages/llm/6-routing/routing.md)) · [8a 에이전틱 AI](docs/stages/llm/8a-agent/README.md)([상세](docs/stages/llm/8a-agent/agent.md))
- 가이드: [아키텍처](docs/guides/architecture.md) · [API](docs/guides/api.md) · [화면(UI)](docs/guides/ui.md) · [데이터 처리](docs/guides/data-processing.md) · [배포 · 운영](docs/guides/deploy.md) · [LLM 연결](docs/guides/llm.md) · [GPU 설치](docs/guides/gpu.md) · [문제 해결](docs/guides/troubleshooting.md)
- 기록: [모델 검증과 실측](docs/records/model-verification.md) · [파인튜닝 실행 기록](docs/stages/llm/5-finetune/finetune.md#실행-기록)

## 개발

```bash
uv run pytest -q             # 테스트 (실제 모델 다운로드 없음, Qdrant 는 메모리 모드)
# pgvector·MariaDB 어댑터까지 검사하려면 컨테이너를 띄우고:
# TEST_PGVECTOR_URL=postgresql://embedding:embedding@localhost:5433/embedding_lab TEST_MARIADB_URL=mysql://embedding:embedding@localhost:3307/embedding_lab uv run pytest -q
uv run python -m alembic revision --autogenerate -m "설명"   # DB 스키마 변경 시
uv run ruff check app tests  # 린트
uv run ruff format app tests # 포맷
uv run python scripts/gen_docs.py    # 레지스트리를 고쳤으면 생성 문서 · 이 README 의 맵 표 다시 만들기
uv run python scripts/check_docs.py  # 문서의 경로 · 화면 주소가 지금 코드와 맞는지 (테스트에도 포함)
```

코드를 바꾸면 같은 커밋에서 문서도 고칩니다 — 무엇을 바꾸면 어디를 고치는지는 [아키텍처 · 문서와 코드 맞추기](docs/guides/architecture.md#문서와-코드-맞추기).

변경 사항은 [CHANGELOG.md](CHANGELOG.md)에 기록합니다. 버전은 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다 — 버그 수정 · 문서 · 작은 개선은 패치(`0.3.1`), 새 기능 · 새 단계 · 새 화면은 마이너(`0.4.0`), 호환이 깨지는 큰 변경(API · 설정 이름 · 데이터 구조)은 메이저(`1.0.0`). 작업 묶음이 끝날 때마다 태그와 릴리스를 만듭니다.

## 라이선스

**이 프로젝트의 소스 코드와 문서는 [MIT License](LICENSE)로 배포됩니다.**

**임베딩 모델의 라이선스는 이와 별도입니다.**
- 이 저장소에는 모델 가중치나 모델 코드가 포함되어 있지 않습니다. 앱은 사용자가 요청할 때 Hugging Face Hub에서 모델을 내려받아 로컬에서 실행할 뿐 재배포하지 않습니다.
- 각 모델은 제공자가 정한 고유 라이선스를 따르며, MIT 라이선스가 모델에 적용되지 않습니다. 모델을 사용하기 전에 해당 모델 카드의 라이선스를 직접 확인하세요. 카탈로그의 라이선스 표기([docs/stages/llm/1-embedding/models.md](docs/stages/llm/1-embedding/models.md), 앱의 모델 화면)는 참고용이며 변경될 수 있습니다.
- 특히 다음 모델은 상업적 사용이 제한되거나 별도 조건이 있습니다.

| 라이선스 | 해당 모델 (카탈로그 기준) |
|---|---|
| CC-BY-NC-4.0 (비상업) | Jina Embeddings v3, v5 Text Small/Nano, v5 Omni Small, Jina Reranker v2 Base Multilingual |
| NVIDIA Custom (비상업) | Llama-Embed-Nemotron 8B |
| Gemma Terms of Use (동의 필요, gated) | EmbeddingGemma 300M |
| LFM Open License v1.0 | LFM2.5-Embedding 350M |
| OpenMDW-1.1 | Nemotron-3-Embed 1B / 8B, Llama-Nemotron Rerank 1B v2 |

그 밖의 모델은 대부분 Apache-2.0 또는 MIT이지만, 역시 모델별로 확인하세요.
