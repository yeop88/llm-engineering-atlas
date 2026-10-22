<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# VL4 · OCR (OCR)

**상태: ⬜ 예정** — 영역 안의 글자 · 코드를 읽고 알려진 목록에 맞춘다

## 원리

OCR 은 영역 안의 글자를 읽는 것입니다. 표시창 코드 · 모델명은 알려진 목록에 맞춰(0/O · 8/B) 고치고, 고쳤다는 사실을 남깁니다.

## 왜 하는가

코드 하나를 잘못 읽으면(0 과 O, 8 과 B) 전혀 다른 매뉴얼 항목으로 가 틀린 조치를 안내합니다.

## 어떻게 (이 앱에서)

- (기반) OCR(D2) · 코드 보정(AS4)
- (예정) 영역 OCR · 보정 · 읽기 정확도

## 화면

- 아직 테스트 화면이 없습니다. 단계 소개는 앱의 `/stages/vl_ocr` 에서 볼 수 있습니다.

## 앞으로 할 일

- 영역 OCR · 보정 · 읽기 정확도

## 상세 문서

- [이미지 · Vision-Language 맵](../../../maps/vision.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [D2 파싱 (HWP · PDF · DOCX · OCR)](../../docintel/d2-parse/README.md) — 문서 처리 (Document Intelligence) 맵 · ✅ 구현됨
- [AS4 오류 사진 진단](../../as-service/as4-photo/README.md) — 서비스 시나리오: 고객 AS 상담 맵 · ✅ 구현됨

---

← [VL3 객체 · 영역 인식](../vl3-detect/README.md) · [전체 맵](../../../maps/vision.md) · [VL5 관계 추론](../vl5-relation/README.md) →
