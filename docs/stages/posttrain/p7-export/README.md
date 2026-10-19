<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry.py)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# P7 · 배포 형식 변환 (GGUF · 양자화) (Export & quantize)

**상태: 🟡 기초 있음** — 학습한 모델을 GGUF 로 바꾸고 양자화해 llama-server 에 올린다

## 원리

학습 결과(Hugging Face 형식 · 어댑터)를 llama.cpp 의 GGUF 로 변환하고, 비트 수를 골라 양자화한 뒤 품질을 다시 잽니다.

## 왜 하는가

학습한 모델도 이 PC 에서 돌리려면 GGUF · 4비트가 필요합니다. 양자화가 학습 효과를 지우지 않는지 확인해야 합니다.

## 어떻게 (이 앱에서)

- (있음) GGUF 비트별 품질 · 속도 비교(QAT Q4_0 ≈ Q8_0), llama-server 실행 명령 생성
- (예정) 변환 · 양자화 파이프라인, 학습 효과 유지 확인

## 화면

- 아직 테스트 화면이 없습니다. 단계 소개는 앱의 `/stages/pt_export` 에서 볼 수 있습니다.

## 앞으로 할 일

- 변환 · 양자화 파이프라인

## 상세 문서

- [후학습 (Post-training) 맵](../../../maps/posttrain.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [7b 양자화](../../llm/7b-quant/README.md) — LLM 시스템 엔지니어링 맵 · ✅ 구현됨

---

← [P6 후학습 평가 · 안전성](../p6-eval/README.md) · [전체 맵](../../../maps/posttrain.md)
