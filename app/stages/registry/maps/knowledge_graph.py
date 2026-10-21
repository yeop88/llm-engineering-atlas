"""지식 그래프 · GraphRAG 맵 — 맵 정의와 단계. 화면 · 메뉴 · 문서가 모두 여기서 나온다(scripts/gen_docs.py).

구축은 탑다운(요구사항 → 온톨로지)과 바텀업(추출)을 섞는다. 첫 적용 도메인은 이미 있는 법률 공개 자료(법령 6 · 판례 164) —
판례마다 참조조문이 있어 '판례 -인용-> 조문' 관계를 추출 없이 바로 만들 수 있다.
"""

from app.stages.registry.model import DONE, Map, Page, Stage

MAP = Map("kg", "지식 그래프 · GraphRAG 맵", "/maps/knowledge-graph", "docs/maps/knowledge-graph.md", template="maps/knowledge_graph.html", summary=
        "온톨로지 설계 → 추출 · 융합 → 그래프 DB → GraphRAG — 개념과 관계를 구조로 저장해 다단계 · 집계 · 전체 요약 질문에 답하는 흐름",
        diagram="[요구사항 정의] → [온톨로지 설계] → [데이터 추출 (ETL · LLM)] → [지식 융합 · 정제]\n"
        "                                        ↓\n"
        "                              [그래프 DB (Neo4j)]\n"
        "                                        ↓\n"
        "  GraphRAG: [Text2Cypher] · [그래프 하이브리드 검색] · [글로벌 커뮤니티 요약]")  # fmt: skip

STAGES: list[Stage] = [
    Stage(
        key="kg_requirements",
        pages=[Page("kg_cq", "/kg/explore#cq", "역량 질문", "그래프가 답해야 할 질문 15개 · 기대 Cypher")],
        no="K1",
        title="요구사항 정의",
        short="요구사항",
        en="Competency questions",
        status=DONE,
        builds_on=["ev_sets"],
        flow="kg",
        map="kg",
        summary="지식 그래프가 답해야 할 업무 질문 10~15개로 그래프의 범위를 정한다",
        principle="역량 질문(Competency Questions)은 '이 그래프로 무엇에 답할 수 있어야 하는가'를 질문 목록으로 적은 것입니다. "
        "어떤 개념 · 관계 · 속성이 필요한지는 이 질문들에서 거꾸로 정해지고, 완성된 그래프가 질문에 실제로 답하는지가 검수 기준이 됩니다.",
        why="범위를 정하지 않고 '문서에 있는 것을 전부' 그래프로 만들면 개념이 끝없이 늘고 관계 이름이 제각각이 되어 쿼리할 수 없는 그래프가 됩니다. "
        "질문이 먼저 있어야 온톨로지를 작게 시작해 필요할 때 넓힐 수 있습니다.",
        how=[
            "법률 역량 질문 15개(한 단계 조회 · 여러 단계 · 집계 · 없는 것 찾기)와 기대 Cypher — 벡터 RAG 가 답하지 못하는 집계 · 없는 것 찾기를 따로 표시",
            "질문마다 쓰는 클래스 · 관계가 온톨로지(K2)의 범위, 기대 Cypher 결과가 Text2Cypher(K6)의 정답",
        ],
        plans=["역량 질문을 실제 업무 질문으로 늘리기"],
        docs=[
            ("지식 그래프 · GraphRAG — 구축 · Cypher · 그래프 확장 · 실측", "docs/stages/knowledge-graph/k5-graph-db/graphrag.md"),
            ("지식 그래프 · GraphRAG 맵", "docs/maps/knowledge-graph.md"),
        ],
    ),
    Stage(
        key="ontology",
        pages=[Page("kg_build", "/kg/build", "그래프 구축", "온톨로지 · 추출 · 쟁점 합치기 · 적재", "kg/build.html")],
        no="K2",
        title="온톨로지 설계",
        short="온톨로지",
        en="Ontology design",
        status=DONE,
        builds_on=["rag"],
        flow="kg",
        map="kg",
        summary="도메인의 개념(클래스) · 속성 · 관계와 그 규칙을 기계가 읽는 스키마로 정의한다",
        principle="온톨로지는 지식 그래프의 설계도입니다. 어떤 클래스(개념)가 있고, 각 클래스가 어떤 속성(Property)과 관계(Relationship)를 갖는지, "
        "관계의 방향 · 개수 · 값의 형식 같은 규칙을 정합니다. W3C 표준으로는 데이터 모델 RDF, 개념 · 관계 정의 OWL, 검증 규칙 SHACL 이 있고, "
        "속성 그래프(Neo4j)에서는 노드 레이블 · 관계 타입 · 제약 조건으로 같은 일을 합니다.",
        why="추출(K3)과 융합(K4)이 같은 설계도를 따라야 '판례가 조문을 인용한다'는 사실이 문서마다 다른 이름의 관계로 흩어지지 않습니다. "
        "검증 규칙이 있어야 잘못 추출된 관계(조문이 판례를 인용 등)를 저장 전에 걸러 정합성을 지킬 수 있습니다.",
        how=[
            "법률 온톨로지 v1(presets/legal_ontology.json): 클래스 5(법령 · 조문 · 판례 · 쟁점 · 커뮤니티) · 관계 6(속함 · 참조 · 인용 · 판례 인용 · 다룸 · 구성원)",
            "추출 결과 검증(클래스 · 관계 방향 · 필수 속성), Text2Cypher 스키마 설명 · 화면이 모두 이 파일에서 나옴",
        ],
        plans=["다른 도메인 온톨로지(AS 매뉴얼: 제품 · 오류 코드 · 조치)"],
        docs=[
            ("지식 그래프 · GraphRAG — 구축 · Cypher · 그래프 확장 · 실측", "docs/stages/knowledge-graph/k5-graph-db/graphrag.md"),
            ("지식 그래프 · GraphRAG 맵", "docs/maps/knowledge-graph.md"),
        ],
    ),
    Stage(
        key="kg_extract",
        pages=[Page("kg_extract", "/kg/build#extract", "데이터 추출", "정형 매핑 + LLM 쟁점")],
        builds_on=["rag"],
        no="K3",
        title="데이터 추출",
        short="추출",
        en="ETL & LLM extraction",
        status=DONE,
        flow="kg",
        map="kg",
        summary="정형 데이터는 스키마 매핑으로, 비정형 문서는 LLM 으로 [주어-관계-목적어] 트리플을 뽑는다",
        principle="정형 데이터(RDB · CSV)는 테이블 열을 온톨로지의 클래스 · 속성 · 관계에 대응시켜(매핑) 그대로 옮깁니다. "
        "비정형 문서(보고서 · 판결문)는 LLM 으로 개체명 인식(NER)과 관계 추출(RE)을 해 [주어-관계-목적어] 트리플을 만듭니다. 추출 결과에는 근거 문장 · 문서를 함께 남깁니다.",
        why="그래프의 품질은 추출에서 정해집니다. 정형 데이터가 있으면 추출보다 매핑이 정확하고 싸므로 먼저 쓰고, LLM 추출은 매핑으로 얻을 수 없는 관계에만 씁니다. "
        "근거를 남겨야 GraphRAG 답변이 RAG 처럼 출처를 댈 수 있습니다.",
        how=[
            "정형: 법령 조문 머리 · 시행령의 '법 제N조' · 「법령」 제N조 · 판례 【참조조문】 · 【참조판례】 → 노드 · 관계(LLM 없이)",
            "참조조문 전용 파서: 법령 이름 안의 띄어쓰기('여객자동차 운수사업법') · 개정 연혁 괄호 · 앞 조각의 법령 이어 쓰기 — 공용 인용 정규식은 이름이 잘려 법령이 잘못 묶였다",
            "비정형: 판시사항에서 LLM 으로 쟁점 1~3개(형식이 어긋나면 버림), 자료에 본문이 없는 인용 대상은 바깥(external) 노드로",
        ],
        plans=["LLM 추출 정확도 사람 판정 표본"],
        docs=[
            ("지식 그래프 · GraphRAG — 구축 · Cypher · 그래프 확장 · 실측", "docs/stages/knowledge-graph/k5-graph-db/graphrag.md"),
            ("지식 그래프 · GraphRAG 맵", "docs/maps/knowledge-graph.md"),
        ],
    ),
    Stage(
        key="kg_fusion",
        pages=[Page("kg_fusion", "/kg/build#fusion", "지식 융합", "쟁점 합치기 · 이름 정규화")],
        builds_on=["rag", "apps"],
        no="K4",
        title="지식 융합 · 정제",
        short="융합 · 정제",
        en="Knowledge fusion",
        status=DONE,
        flow="kg",
        map="kg",
        summary="다른 이름의 같은 개체를 하나로 묶고(개체 정규화) 중복 · 충돌을 정리해 그래프를 완성한다",
        principle="여러 문서에서 나온 '미국' · 'USA' · 'United States' 처럼 같은 대상을 가리키는 개체를 하나의 노드로 묶습니다(개체 정규화 · 연결). "
        "이름 규칙 · 사전 · 임베딩 유사도 · LLM 판단을 섞어 후보를 찾고, 같은 관계의 중복과 서로 어긋나는 사실을 정리합니다.",
        why="정규화하지 않으면 같은 조문이 '근로기준법 제23조' · '근기법 23조' · '같은 법 제23조 제1항' 처럼 여러 노드로 갈라져, "
        "다단계 탐색이 중간에 끊기고 집계가 틀립니다. 그래프의 연결이 곧 답이므로 여기서의 오류가 그대로 오답이 됩니다.",
        how=[
            "조문 · 법령 이름은 추출에서 규칙으로 정규화(띄어쓰기 · 가운뎃점 · '구' 법 · 조문 번호)",
            "쟁점: 낱말 끝 조사 · 띄어쓰기를 뺀 글자가 같으면 합치고, 그 밖에는 임베딩 유사도 0.88 이상끼리 합침 — 합친 기록을 화면에",
        ],
        plans=["합치기 정밀도 사람 판정"],
        docs=[
            ("지식 그래프 · GraphRAG — 구축 · Cypher · 그래프 확장 · 실측", "docs/stages/knowledge-graph/k5-graph-db/graphrag.md"),
            ("지식 그래프 · GraphRAG 맵", "docs/maps/knowledge-graph.md"),
        ],
    ),
    Stage(
        key="graph_db",
        pages=[
            Page(
                "kg_explore",
                "/kg/explore",
                "그래프 탐색 · Cypher",
                "노드 · 이웃 탐색, Cypher 엔진(Neo4j · FalkorDB) · Text2Cypher, 역량 질문",
                "kg/explore.html",
            )
        ],
        builds_on=["rag"],
        no="K5",
        title="그래프 DB",
        short="그래프 DB",
        en="Graph database (Neo4j · FalkorDB)",
        status=DONE,
        flow="kg",
        map="kg",
        summary="노드와 관계로 저장하고, JOIN 없이 이웃을 따라가는 다단계 탐색과 벡터 검색을 한 곳에서 한다",
        principle="그래프 DB 는 데이터를 표가 아니라 노드(Node)와 관계(Relationship)로 저장합니다. Neo4j 는 노드가 이웃의 위치를 직접 가리키는 방식"
        "(Index-free Adjacency)이라, 관계를 여러 번 건너는 질의(Multi-hop)를 표 JOIN 없이 이웃을 따라가며 처리합니다. 질의 언어 Cypher 는 "
        "`(판례)-[:인용]->(조문)` 처럼 그래프 패턴을 그림처럼 씁니다. 노드 속성에 임베딩을 넣고 벡터 인덱스로 찾을 수도 있습니다.",
        why="관계형 DB 에서 '판례 → 인용 조문 → 그 조문을 위임한 시행령 → 그 시행령을 인용한 다른 판례' 같은 질의는 JOIN 이 단계마다 늘어 느려지고 쓰기도 어렵습니다. "
        "벡터 인덱스가 같은 DB 에 있으면 '비슷한 글 찾기'와 '연결 따라가기'를 한 질의로 합칠 수 있어 GraphRAG(K7)에 맞습니다.",
        how=[
            "내장 그래프 저장소(앱 DB 의 노드 · 관계 표, 마이그레이션 0012)가 원본 — 서버 없이도 이웃 확장 · 커뮤니티가 돈다",
            "Neo4j(docker compose --profile neo4j, 5.26 LTS)로 통째로 옮겨 Cypher 실행, 같은 자료를 다시 적재해도 개체 · 관계가 늘지 않음",
            "두 번째 엔진 FalkorDB(Redis 모듈, OpenCypher)에도 같은 그래프를 옮겨 같은 역량 질문으로 방언 · 속도 · 무게를 비교",
        ],
        plans=["ArangoDB 등 다른 그래프 DB 어댑터(보류)"],
        docs=[
            ("지식 그래프 · GraphRAG — 구축 · Cypher · 그래프 확장 · 실측", "docs/stages/knowledge-graph/k5-graph-db/graphrag.md"),
            ("지식 그래프 · GraphRAG 맵", "docs/maps/knowledge-graph.md"),
        ],
    ),
    Stage(
        key="text2cypher",
        pages=[Page("kg_cypher", "/kg/explore#cypher", "Text2Cypher", "질문 → Cypher → 결과")],
        builds_on=["agent"],
        no="K6",
        title="Text2Cypher",
        en="Natural language to graph query",
        status=DONE,
        flow="kg",
        map="kg",
        summary="질문을 LLM 이 Cypher 쿼리로 바꿔 그래프 DB 가 정확한 결과 · 집계를 돌려준다",
        principle="LLM 에 그래프 스키마(온톨로지)와 질문을 주고 Cypher 쿼리를 만들게 한 뒤, 그래프 DB 가 실행한 결과로 답합니다. "
        "숫자 · 목록 · 집계는 DB 가 계산하므로 LLM 이 지어낼 여지가 줄어듭니다.",
        why="'작년에 가장 많이 제기된 결함 유형은?', '제23조를 인용한 판례는 몇 건?' 같은 집계 · 필터 질문은 문서 조각을 읽는 벡터 RAG 로는 정확히 답하기 어렵습니다. "
        "대신 쿼리가 틀리면(없는 관계 이름 · 잘못된 방향) 결과가 비거나 엉뚱하므로, 생성한 쿼리를 검증하고 실패하면 다시 만드는 절차가 필요합니다.",
        how=[
            "스키마 설명은 온톨로지에서 자동, 예시 2개, 읽기 쿼리만(실행 전에 EXPLAIN 으로 쿼리 종류 확인 — 키워드 검사는 우회가 쉬움)",
            "오류 · 빈 결과면 이유를 알려 다시 씀(최대 2번), 역량 질문 15개로 정확 일치 · 겹침 측정",
        ],
        plans=["큰 모델과 비교", "자주 틀리는 유형 예시 보강"],
        docs=[
            ("지식 그래프 · GraphRAG — 구축 · Cypher · 그래프 확장 · 실측", "docs/stages/knowledge-graph/k5-graph-db/graphrag.md"),
            ("지식 그래프 · GraphRAG 맵", "docs/maps/knowledge-graph.md"),
        ],
    ),
    Stage(
        key="graph_hybrid",
        pages=[Page("kg_rag", "/kg/rag", "GraphRAG", "그래프 확장 검색 · 답변, 벡터 대비 비교, 커뮤니티 요약", "kg/rag.html")],
        builds_on=["rag", "rerank"],
        no="K7",
        title="그래프 하이브리드 검색",
        short="하이브리드 검색",
        en="Vector + graph retrieval",
        status=DONE,
        flow="kg",
        map="kg",
        summary="벡터 검색으로 찾은 청크에서 연결된 개체 · 관계(서브그래프)를 함께 가져와 답변 맥락을 넓힌다",
        principle="질문과 비슷한 문서 청크를 벡터로 먼저 찾고(LLM 맵의 2 RAG 검색과 같음), 그 청크와 연결된 개체 · 관계를 그래프에서 한두 단계 따라가 "
        "'이 판례는 이 조문을 인용했고, 그 조문은 이 시행령에 위임했다' 같은 맥락을 근거에 덧붙입니다.",
        why="벡터 RAG 는 질문과 글이 비슷한 조각만 가져와, 답에 필요한 연결된 사실(다른 문서에 있는 관련 조문 · 판례)을 놓칩니다. "
        "법률 재측정에서 여러 문서 질문의 검색 nDCG 가 37 로 가장 낮았던 것이 이 한계입니다.",
        how=[
            "검색 상위 문서 → 그래프 노드 → 2단계 이웃: 인용한 조문 · 판례, 같은 조문을 인용한 다른 판례(공동 인용), 같은 쟁점",
            "넓힌 문서는 연결 수로 줄 세워 벡터 결과 뒤에 붙이고, 문서 사이 관계를 '관계 요약'으로 답변 프롬프트에(검증 · 가드레일 · 요청 기록은 같음)",
            "평가 세트로 '벡터 상위 k' vs '벡터 k−3 + 그래프 3' 비교(정답 하나라도 · 정답 모두 · MRR)",
        ],
        plans=["답변 품질 비교(LLM 판정)"],
        docs=[
            ("지식 그래프 · GraphRAG — 구축 · Cypher · 그래프 확장 · 실측", "docs/stages/knowledge-graph/k5-graph-db/graphrag.md"),
            ("지식 그래프 · GraphRAG 맵", "docs/maps/knowledge-graph.md"),
            ("LLM 맵 · 2 RAG 검색", "docs/stages/llm/2-rag/rag.md"),
        ],
    ),
    Stage(
        key="community_summary",
        pages=[Page("kg_communities", "/kg/rag#communities", "커뮤니티 요약", "묶음 요약 · 전체 질문")],
        builds_on=["apps"],
        no="K8",
        title="글로벌 커뮤니티 요약",
        short="커뮤니티 요약",
        en="Global community summaries (GraphRAG)",
        status=DONE,
        flow="kg",
        map="kg",
        summary="그래프를 계층적 커뮤니티로 나눠 미리 요약해 두고, 전체 주제 · 추세 질문은 요약들을 모아 답한다",
        principle="그래프를 연결이 촘촘한 묶음(커뮤니티)으로 나누고(Leiden 등), 묶음마다 LLM 으로 요약을 미리 만들어 둡니다. 큰 묶음 안에 작은 묶음이 있는 계층 구조입니다. "
        "'이 자료 전체의 주요 쟁점은?' 같은 질문에는 특정 노드를 찾는 대신 관련 커뮤니티 요약들을 모아 답합니다(Microsoft GraphRAG 의 Global Search 방식).",
        why="벡터 RAG 와 Text2Cypher 는 모두 '어딘가에 있는 특정 사실'을 찾는 방식이라, 책 한 권 분량 전체를 훑어야 하는 요약 · 추세 질문에는 약합니다. "
        "대신 요약을 미리 만드는 비용이 크고(LLM 호출이 커뮤니티 수만큼), 자료가 바뀌면 다시 만들어야 합니다.",
        how=[
            "조문 · 판례 · 쟁점 그래프의 Louvain 커뮤니티(법령 노드 · '속함'은 빼야 법령 목차가 아닌 '같은 문제' 묶음이 됨), 큰 묶음부터 LLM 요약을 커뮤니티 노드로 저장",
            "전체 질문은 질문과 가까운 요약 4개를 골라 한 번에 답하고 [C1] 처럼 묶음을 인용",
        ],
        plans=["전체 요약 질문 평가 세트"],
        docs=[
            ("지식 그래프 · GraphRAG — 구축 · Cypher · 그래프 확장 · 실측", "docs/stages/knowledge-graph/k5-graph-db/graphrag.md"),
            ("지식 그래프 · GraphRAG 맵", "docs/maps/knowledge-graph.md"),
        ],
    ),
]
