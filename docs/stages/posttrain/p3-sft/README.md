<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry.py)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# P3 · SFT (지도 미세조정) (Supervised fine-tuning)

**상태: ⬜ 예정** — 좋은 질문-답 예시로 LLM 을 추가 학습해 답 형식 · 인용 습관 · 도메인 말투를 맞춘다

## 원리

SFT 는 (지시, 좋은 답) 쌍으로 모델을 추가 학습하는 것입니다. 전체 가중치 대신 어댑터(LoRA)만 학습하면 GPU 메모리가 크게 줄어듭니다.

## 왜 하는가

프롬프트로 고치기 어려운 습관(근거 번호 다는 형식 · 거절 문구 · 간결함)을 모델 자체에 넣습니다. 이 PC(CPU)에서는 현실적이지 않아 GPU 환경이 필요합니다.

## 어떻게 (이 앱에서)

- (있음) 대화형 JSONL 학습 데이터(LLM 증류)
- (예정) GPU 환경 LoRA SFT(TRL 등), 학습 전후 같은 평가 세트 비교

## 화면

- 아직 테스트 화면이 없습니다. 단계 소개는 앱의 `/stages/pt_sft` 에서 볼 수 있습니다.

## 앞으로 할 일

- LoRA SFT (GPU)

## 상세 문서

- [후학습 (Post-training) 맵](../../../maps/posttrain.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [7a 지식 증류](../../llm/7a-distill/README.md) — LLM 시스템 엔지니어링 맵 · ✅ 구현됨

---

← [P2 선별 · 누수 방지](../p2-select/README.md) · [전체 맵](../../../maps/posttrain.md) · [P4 선호 학습 (DPO 등)](../p4-pref/README.md) →
