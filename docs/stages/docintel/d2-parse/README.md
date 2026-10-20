<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# D2 · 파싱 (HWP · PDF · DOCX · OCR) (Parsing & OCR)

**상태: ✅ 구현됨** — 형식마다 맞는 파서로 글 · 구조를 뽑고, 스캔 문서는 OCR 로 읽는다

## 원리

파싱은 파일 형식(HWP · HWPX · PDF · DOCX · HTML)마다 본문 · 제목 · 페이지 · 표를 뽑는 단계입니다. 글자가 없는 스캔 PDF 는 OCR(광학 문자 인식)로 이미지에서 글을 읽어야 합니다.

## 왜 하는가

한국 공공 · 사내 문서는 HWP 가 많고, 스캔 PDF 도 흔합니다. 파싱에서 빠진 글은 검색 · 답변 어디서도 되살릴 수 없습니다.

## 어떻게 (이 앱에서)

- 파싱 점검: 깨진 글자 비율 · 빈 페이지 · 짧은 페이지로 문서별 경고
- OCR: PDF 페이지를 그림으로(pypdfium2) → 비전 LLM 이 글 읽기, 정답 글이 있으면 글자 정확도
- (있음) HWP · HWPX · PDF · DOCX · TXT · MD 파서

## 화면

- `/docintel/parsing` — **파싱 · OCR · 표**: 깨진 글자 · 빈 페이지 점검, 비전 LLM OCR, 표 · 그림 추출

## 앞으로 할 일

- 전용 OCR 엔진과 비교

## 상세 문서

- [파싱 점검 · OCR · 표 · 그림](parsing.md)
- [문서 처리 (Document Intelligence) 맵](../../../maps/docintel.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [2 RAG 검색](../../llm/2-rag/README.md) — LLM 시스템 엔지니어링 맵 · ✅ 구현됨

---

← [D1 수집 · 연결](../d1-ingest/README.md) · [전체 맵](../../../maps/docintel.md) · [D3 레이아웃 · 표 · 그림 추출](../d3-layout/README.md) →
