<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# VL2 · 전처리 (Preprocessing)

**상태: ⬜ 예정** — 기울기 · 밝기 · 반사 · 잘라내기로 읽기 좋게 만든다

## 원리

전처리는 기울기 보정 · 밝기 맞추기 · 반사 줄이기 · 관심 영역 잘라내기입니다. 표시창처럼 작은 영역은 잘라 키워야 읽힙니다.

## 왜 하는가

같은 VLM 도 전처리에 따라 코드 읽기 정확도가 크게 다릅니다(사진 진단 실측의 흐림 · 반사 조건).

## 어떻게 (이 앱에서)

- (기반) OCR 전처리(D2)
- (예정) 전처리 단계별 읽기 정확도

## 화면

- 아직 테스트 화면이 없습니다. 단계 소개는 앱의 `/stages/vl_prep` 에서 볼 수 있습니다.

## 앞으로 할 일

- 전처리 단계별 읽기 정확도

## 상세 문서

- [이미지 · Vision-Language 맵](../../../maps/vision.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [D2 파싱 (HWP · PDF · DOCX · OCR)](../../docintel/d2-parse/README.md) — 문서 처리 (Document Intelligence) 맵 · ✅ 구현됨

---

← [VL1 이미지 입력](../vl1-input/README.md) · [전체 맵](../../../maps/vision.md) · [VL3 객체 · 영역 인식](../vl3-detect/README.md) →
