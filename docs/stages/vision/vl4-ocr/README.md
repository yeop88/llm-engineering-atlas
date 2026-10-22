<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# VL4 · OCR (OCR)

**상태: ✅ 구현됨** — 영역 안의 글자 · 코드를 읽고 알려진 목록에 맞춘다

## 원리

OCR 은 영역 안의 글자를 읽는 것입니다. 표시창 코드 · 모델명은 알려진 목록에 맞춰(0/O · 8/B) 고치고, 고쳤다는 사실을 남깁니다.

## 왜 하는가

코드 하나를 잘못 읽으면(0 과 O, 8 과 B) 전혀 다른 매뉴얼 항목으로 가 틀린 조치를 안내합니다.

## 어떻게 (이 앱에서)

- (기반) 문서 OCR(D2) · 사진 진단 코드 맞춤(AS4)
- 표시창 영역 + 여백을 잘라 짧은 변 320px 까지 키워 비전 LLM 에 읽히고, 알려진 코드 목록에 맞춤(고쳤으면 표시) — 표시창을 못 찾으면 사진 전체

## 화면

- `/vision/look#look` — **OCR**: 잘라 키운 표시창만 읽기 · 코드 맞춤

## 상세 문서

- [이미지 · Vision-Language — 입력 확인 · 전처리 · 영역 찾기 · 영역만 읽기 · 꺾임 규칙 · 매뉴얼 근거 답 · 근거 영역, VLM 하나에 vs 나눠서](../vl1-input/vision.md)
- [이미지 · Vision-Language 맵](../../../maps/vision.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [D2 파싱 (HWP · PDF · DOCX · OCR)](../../docintel/d2-parse/README.md) — 문서 처리 (Document Intelligence) 맵 · ✅ 구현됨
- [AS4 오류 사진 진단](../../as-service/as4-photo/README.md) — 서비스 시나리오: 고객 AS 상담 맵 · ✅ 구현됨

---

← [VL3 객체 · 영역 인식](../vl3-detect/README.md) · [전체 맵](../../../maps/vision.md) · [VL5 관계 추론](../vl5-relation/README.md) →
