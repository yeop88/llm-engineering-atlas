<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# PV3 · 변환 파이프라인 (Transform pipeline)

**상태: ✅ 구현됨** — 파싱 · OCR · 표 복원 · 정제의 각 단계를 기록한다

## 원리

변환 파이프라인은 원본이 청크가 되기까지 거친 단계(파싱 · OCR · 표 복원 · 정제 · 중복 제거)와 각 단계의 설정 · 판입니다.

## 왜 하는가

OCR 오류나 표 복원 오류로 생긴 틀린 답은 변환 단계를 알아야 고칩니다.

## 어떻게 (이 앱에서)

- (기반) 파싱(D2) · 레이아웃(D3)
- 문서 메타에 남은 파서 · OCR · 레이아웃 · 정제 기록과 청크 세트의 나눈 방식(전략)을 사슬에 표시

## 화면

- `/provenance/trace#trace` — **변환 파이프라인**: 파서 · OCR · 레이아웃 · 정제 기록

## 앞으로 할 일

- 변환 단계마다 판 · 설정을 따로 남기기(지금은 문서 메타에 있는 것만)

## 상세 문서

- [데이터 계보 · 근거 — 요청 → 청크 → 문서 · 판 사슬 · 주장 나누기 · 표시 일치 · 부딪힘 · 주장 단위 평가 · 실측](../pv1-source/provenance.md)
- [데이터 계보 · 근거 맵](../../../maps/provenance.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [D2 파싱 (HWP · PDF · DOCX · OCR)](../../docintel/d2-parse/README.md) — 문서 처리 (Document Intelligence) 맵 · ✅ 구현됨
- [D3 레이아웃 · 표 · 그림 추출](../../docintel/d3-layout/README.md) — 문서 처리 (Document Intelligence) 맵 · ✅ 구현됨

---

← [PV2 수집 시각 · 판](../pv2-ingest/README.md) · [전체 맵](../../../maps/provenance.md) · [PV4 청크](../pv4-chunk/README.md) →
