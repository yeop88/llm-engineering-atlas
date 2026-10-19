<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry.py)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# D2 · 파싱 (HWP · PDF · DOCX · OCR) (Parsing & OCR)

**상태: 🟡 기초 있음** — 형식마다 맞는 파서로 글 · 구조를 뽑고, 스캔 문서는 OCR 로 읽는다

## 원리

파싱은 파일 형식(HWP · HWPX · PDF · DOCX · HTML)마다 본문 · 제목 · 페이지 · 표를 뽑는 단계입니다. 글자가 없는 스캔 PDF 는 OCR(광학 문자 인식)로 이미지에서 글을 읽어야 합니다.

## 왜 하는가

한국 공공 · 사내 문서는 HWP 가 많고, 스캔 PDF 도 흔합니다. 파싱에서 빠진 글은 검색 · 답변 어디서도 되살릴 수 없습니다.

## 어떻게 (이 앱에서)

- (있음) HWP · HWPX · PDF · DOCX · HTML · 텍스트 파서, 배포용 HWP 감지, 글자 없는 PDF 경고
- (예정) OCR(스캔 PDF · 이미지 속 글자), 파싱 결과 미리 보기 · 빠진 페이지 확인

## 화면

- 아직 테스트 화면이 없습니다. 단계 소개는 앱의 `/stages/doc_parse` 에서 볼 수 있습니다.

## 앞으로 할 일

- OCR
- 파싱 결과 점검 화면

## 상세 문서

- [문서 처리 (Document Intelligence) 맵](../../../maps/docintel.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [2 RAG 검색](../../llm/2-rag/README.md) — LLM 시스템 엔지니어링 맵 · ✅ 구현됨

---

← [D1 수집 · 연결](../d1-ingest/README.md) · [전체 맵](../../../maps/docintel.md) · [D3 레이아웃 · 표 · 그림 추출](../d3-layout/README.md) →
