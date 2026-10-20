"""문서 처리 (Document Intelligence) 맵 — 맵 정의와 단계. 화면 · 메뉴 · 문서가 모두 여기서 나온다(scripts/gen_docs.py)."""

from app.stages.registry.model import DONE, Map, Page, Stage

MAP = Map("docintel", "문서 처리 (Document Intelligence) 맵", "/maps/docintel", "docs/maps/docintel.md",
        summary="수집 → 파싱(HWP · PDF · OCR) → 레이아웃 · 표 · 그림 → 정제 · 중복 · 버전 → 청킹 → 메타데이터 · 증분 갱신 → 품질 점검 — 자료를 제대로 읽는 흐름",
        diagram="[수집 · 연결] → [파싱 (HWP · PDF · DOCX · OCR)] → [레이아웃 · 표 · 그림 추출]\n"
                "                                      ↓\n"
                "[정제 · 중복 · 버전] → [청킹] → [메타데이터 · 증분 갱신]\n"
                "                                      ↓\n"
                "                         [데이터 품질 점검]",
        lead="RAG 의 품질은 검색 모델보다 먼저 '자료를 제대로 읽었는가'에서 정해집니다. 법률 재측정의 문제 상당수가 여기서 났습니다 — 근거 문장이 청크 경계에서 잘리고, 짧은 조문 청크가 35% 였고, 법령 표의 행 반복이 섞였습니다. "
             "이 맵은 원본이 들어와 색인되기 전까지의 처리와 그 점검을 다룹니다.",
        groups=(("읽기", ("doc_ingest", "doc_parse", "doc_layout")),
                ("다듬기", ("doc_clean", "doc_chunk", "doc_meta")),
                ("확인", ("doc_quality",))),
        principles=("통계보다 실제 텍스트를 연다 — 법령 반복 행은 건수 통계로는 보이지 않았다",
                    "근거가 청크에 온전히 들어가는지 잰다 — 생성 근거의 6% 가 원문과 달랐고 일부는 청크 경계 때문",
                    "짧은 청크는 합친다 — merge_below 200 으로 청크 −42%, 품질 동일",
                    "처리 기록은 단계별 건수와 함께 남긴다(data-processing.md)"),
        example="스캔 PDF 규정집: 텍스트가 없으면 OCR → 표는 이미지 청크와 표 구조를 함께 → 조항 단위 청킹 → 개정일 메타데이터 → 개정판이 오면 바뀐 조항만 다시 색인.")  # fmt: skip

STAGES: list[Stage] = [
    Stage(
        key="doc_ingest",
        pages=[
            Page(
                "docintel_sources",
                "/docintel/sources",
                "수집 · 메타 · 증분 갱신",
                "폴더 소스 동기화, 문서 메타데이터, 바뀐 문서만 다시 색인",
                "docintel/sources.html",
            )
        ],
        no="D1",
        title="수집 · 연결",
        short="수집",
        en="Ingestion & connectors",
        status=DONE,
        flow="docintel",
        map="docintel",
        builds_on=["rag"],
        summary="파일 업로드 · 공개 데이터 · 사내 시스템에서 원본을 가져오고 출처를 남긴다",
        principle="수집은 원본을 그대로 가져와 출처 · 시각 · 해시와 함께 저장하는 단계입니다. 같은 파일은 해시로 걸러 중복 색인을 막고, 원본을 남겨 처리 방법이 바뀌면 다시 처리할 수 있게 합니다.",
        why="원본과 출처가 없으면 처리 실수를 고칠 수 없고, 답변의 근거를 원문으로 보여 줄 수 없습니다.",
        how=[
            "폴더 소스(INGEST_ROOTS 안만 — 서버의 아무 폴더나 읽지 못하게) · 파일 패턴 · 주기(분), 파일 sha 로 새 · 바뀜 · 지움 · 그대로 판단",
            "주기 수집(앱 안 1분 주기 스레드) → 바뀐 문서만 증분 갱신",
            "원본 파일을 sha 로 보관(다시 파싱 · OCR 할 때)",
        ],
        plans=["사내 시스템(그룹웨어 · 위키) 연결"],
        docs=[
            ("수집 · 메타데이터 · 증분 갱신", "docs/stages/docintel/d1-ingest/ingest.md"),
            ("문서 처리 (Document Intelligence) 맵", "docs/maps/docintel.md"),
        ],
    ),
    Stage(
        key="doc_parse",
        pages=[
            Page(
                "docintel_parsing",
                "/docintel/parsing",
                "파싱 · OCR · 표",
                "깨진 글자 · 빈 페이지 점검, 비전 LLM OCR, 표 · 그림 추출",
                "docintel/parsing.html",
            )
        ],
        no="D2",
        title="파싱 (HWP · PDF · DOCX · OCR)",
        short="파싱",
        en="Parsing & OCR",
        status=DONE,
        flow="docintel",
        map="docintel",
        builds_on=["rag"],
        summary="형식마다 맞는 파서로 글 · 구조를 뽑고, 스캔 문서는 OCR 로 읽는다",
        principle="파싱은 파일 형식(HWP · HWPX · PDF · DOCX · HTML)마다 본문 · 제목 · 페이지 · 표를 뽑는 단계입니다. 글자가 없는 스캔 PDF 는 OCR(광학 문자 인식)로 이미지에서 글을 읽어야 합니다.",
        why="한국 공공 · 사내 문서는 HWP 가 많고, 스캔 PDF 도 흔합니다. 파싱에서 빠진 글은 검색 · 답변 어디서도 되살릴 수 없습니다.",
        how=[
            "파싱 점검: 깨진 글자 비율 · 빈 페이지 · 짧은 페이지로 문서별 경고",
            "OCR: PDF 페이지를 그림으로(pypdfium2) → 비전 LLM 이 글 읽기, 정답 글이 있으면 글자 정확도",
            "(있음) HWP · HWPX · PDF · DOCX · TXT · MD 파서",
        ],
        plans=["전용 OCR 엔진과 비교"],
        docs=[
            ("파싱 점검 · OCR · 표 · 그림", "docs/stages/docintel/d2-parse/parsing.md"),
            ("문서 처리 (Document Intelligence) 맵", "docs/maps/docintel.md"),
        ],
    ),
    Stage(
        key="doc_layout",
        pages=[Page("docintel_layout", "/docintel/parsing#d-card", "표 · 그림 추출", "문서를 열어 표 · 그림 추출")],
        no="D3",
        title="레이아웃 · 표 · 그림 추출",
        short="레이아웃 · 표",
        en="Layout, tables & figures",
        status=DONE,
        flow="docintel",
        map="docintel",
        builds_on=["multimodal", "mm_rag"],
        summary="제목 · 단락 · 표 · 그림 영역을 나눠, 표는 구조로 · 그림은 이미지 청크로 남긴다",
        principle="레이아웃 분석은 페이지에서 제목 · 단락 · 표 · 그림 · 머리말 영역을 나누는 것입니다. 표는 행 · 열 구조로, 그림은 이미지로 따로 저장하면 글로 뭉개지지 않습니다.",
        why="표를 글로 펴면 행 · 열 관계가 사라져 '3분기 매출' 같은 질문에 답할 수 없습니다. 법령 표의 행 반복 문제도 표 구조를 모르고 처리해서 생겼습니다.",
        how=[
            "pdfplumber 로 표 → 마크다운 표(페이지 글에 '[표 p-n]'으로 넣어 검색 · 인용)",
            "그림 → 미디어 청크(1장 = 1청크, 멀티모달 검색 · 답변에 첨부)",
        ],
        plans=["HWP 표 구조"],
        docs=[
            ("파싱 점검 · OCR · 표 · 그림", "docs/stages/docintel/d2-parse/parsing.md"),
            ("문서 처리 (Document Intelligence) 맵", "docs/maps/docintel.md"),
        ],
    ),
    Stage(
        key="doc_clean",
        pages=[
            Page(
                "docintel_quality",
                "/docintel/quality",
                "정제 · 품질 점검",
                "머리말 · 꼬리말 · 거의 같은 문서 · 판 정리, 청크 품질 · 근거 보존",
                "docintel/quality.html",
            )
        ],
        no="D4",
        title="정제 · 중복 · 버전",
        short="정제 · 중복",
        en="Cleaning, dedup & versions",
        status=DONE,
        flow="docintel",
        map="docintel",
        builds_on=["rag", "apps"],
        summary="머리말 · 반복 행 같은 잡음을 걷고, 거의 같은 문서 · 개정판을 정리한다",
        principle="정제는 검색을 방해하는 잡음(머리말 · 쪽 번호 · 반복 행 · 목차)을 걷는 것이고, 중복 정리는 같은 내용의 다른 파일 · 개정 전후판을 찾아 하나만 쓰거나 버전으로 묶는 것입니다.",
        why="잡음 · 중복은 검색 결과 상위를 차지해 정답을 밀어냅니다. 개정판이 섞이면 옛 조항으로 답합니다.",
        how=[
            "머리말 · 꼬리말(여러 페이지에 반복되는 줄) 지우기",
            "거의 같은 문서(shingle Jaccard) 찾기, 같은 제목의 판 묶기 → 옛 판에 superseded 표시(최신판만 검색)",
        ],
        plans=["문단 단위 중복"],
        docs=[
            ("정제 · 청크 품질 · 근거 보존", "docs/stages/docintel/d4-clean/quality.md"),
            ("문서 처리 (Document Intelligence) 맵", "docs/maps/docintel.md"),
        ],
    ),
    Stage(
        key="doc_chunk",
        pages=[Page("docintel_chunks", "/docintel/quality#chunks", "청크 품질", "길이 분포 · 끊긴 청크")],
        no="D5",
        title="청킹",
        short="청킹",
        en="Chunking",
        status=DONE,
        flow="docintel",
        map="docintel",
        builds_on=["rag"],
        summary="문서를 검색 단위로 자르되 근거 문장이 경계에서 잘리지 않게 한다",
        principle="청킹은 문서를 임베딩 · 검색 단위로 자르는 것입니다. 크기 · 겹침 · 구조(조문 · 제목) 기준 · 짧은 청크 합치기를 정하고, 근거 문장이 청크 하나에 온전히 들어가는 비율로 평가합니다.",
        why="청크가 너무 길면 질문과 무관한 글이 섞이고, 너무 짧거나 경계가 나쁘면 근거가 잘립니다. 법률 자료에서 짧은 청크가 35% 였고, 일부 근거는 경계에 걸쳐 어느 청크에도 온전히 없었습니다.",
        how=[
            "청크 품질 보고: 길이 분포 · 너무 짧은 · 너무 긴 · 문장 중간에서 끊긴 청크",
            "근거 보존: 평가 세트의 근거 문장이 한 청크 안에 온전히 들어간 비율",
            "(있음) 재귀 · 고정 · 문장 · 법률 구조 · 페이지 청킹, 미리보기",
        ],
        plans=["청킹 자동 추천"],
        docs=[
            ("정제 · 청크 품질 · 근거 보존", "docs/stages/docintel/d4-clean/quality.md"),
            ("문서 처리 (Document Intelligence) 맵", "docs/maps/docintel.md"),
        ],
    ),
    Stage(
        key="doc_meta",
        pages=[Page("docintel_meta", "/docintel/sources#meta", "문서 메타데이터", "메타 편집 · 증분 갱신")],
        no="D6",
        title="메타데이터 · 증분 갱신",
        short="증분 갱신",
        en="Metadata & incremental updates",
        status=DONE,
        flow="docintel",
        map="docintel",
        builds_on=["rag"],
        summary="문서 날짜 · 종류 · 권한 메타데이터를 붙이고, 바뀐 문서만 다시 색인한다",
        principle="메타데이터(작성일 · 시행일 · 종류 · 부서 · 권한)는 검색 필터와 최신성 판단에 쓰입니다. 증분 갱신은 문서가 바뀌면 그 문서의 청크만 다시 만들어 색인을 최신으로 유지하는 것입니다.",
        why="전체 다시 색인은 이 PC 에서 법률 자료 하나에 44분이 걸렸습니다. 자주 바뀌는 사내 문서를 매번 전부 다시 할 수는 없습니다.",
        how=[
            "문서 메타(종류 · 부서 · 제품 모델 · 날짜 · 권한 · 판) 편집 · 모음, 검색 설정의 filters(종류 · 부서 · 제품 · 날짜 · 최신판만)",
            "증분 갱신: 바뀐 시각(changed_at)이 청크 세트 갱신 시각보다 뒤인 문서만 다시 청크 · 임베딩",
        ],
        plans=["메타 자동 추출(LLM)"],
        docs=[
            ("수집 · 메타데이터 · 증분 갱신", "docs/stages/docintel/d1-ingest/ingest.md"),
            ("문서 처리 (Document Intelligence) 맵", "docs/maps/docintel.md"),
        ],
    ),
    Stage(
        key="doc_quality",
        pages=[Page("docintel_preservation", "/docintel/quality#chunks", "근거 보존", "평가 세트 근거가 한 청크에 남았는지")],
        no="D7",
        title="데이터 품질 점검",
        short="품질 점검",
        en="Data quality checks",
        status=DONE,
        flow="docintel",
        map="docintel",
        builds_on=["rag", "ev_sets"],
        summary="처리 단계별 건수 · 길이 분포 · 근거 보존을 점검하고 처리 기록을 남긴다",
        principle="데이터 품질 점검은 수집 · 정제 · 청킹 각 단계에서 남은 건수, 길이 분포, 이상한 글(반복 · 깨진 글자), 평가 근거의 보존을 확인하고 그 결과를 기록하는 것입니다.",
        why="통계만 보면 문제를 못 찾고(법령 반복 행), 기록이 없으면 같은 실수를 반복합니다.",
        how=[
            "컬렉션 상태: 갱신이 필요한 청크 세트 · 문서 수",
            "청크 품질 · 근거 보존 보고(D5)와 파싱 점검(D2)을 한 화면에",
        ],
        plans=["품질 점수 추세"],
        docs=[
            ("정제 · 청크 품질 · 근거 보존", "docs/stages/docintel/d4-clean/quality.md"),
            ("문서 처리 (Document Intelligence) 맵", "docs/maps/docintel.md"),
        ],
    ),
]
