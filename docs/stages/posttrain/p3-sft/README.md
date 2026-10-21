<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# P3 · SFT (지도 미세조정) (Supervised fine-tuning)

**상태: ✅ 구현됨** — 좋은 질문-답 예시로 LLM 을 추가 학습해 답 형식 · 인용 습관 · 도메인 말투를 맞춘다

## 원리

SFT 는 (지시, 좋은 답) 쌍으로 모델을 추가 학습하는 것입니다. 전체 가중치 대신 어댑터(LoRA)만 학습하면 GPU 메모리가 크게 줄어듭니다.

## 왜 하는가

프롬프트로 고치기 어려운 습관(근거 번호 다는 형식 · 거절 문구 · 간결함)을 모델 자체에 넣습니다. 이 PC(CPU)에서는 현실적이지 않아 GPU 환경이 필요합니다.

## 어떻게 (이 앱에서)

- 작은 LLM(POSTTRAIN_BASE_MODEL, 기본 Qwen3-0.6B)에 LoRA(q · k · v · o) — transformers + peft 로 직접 돌고(TRL 없이) 걸음마다 손실을 작업 진행에
- 손실은 답(assistant) 부분에만 — 근거 · 질문까지 맞히게 하면 근거를 외우는 쪽으로 학습
- 길면 근거 앞부분을 잘라 답을 남김, Qwen3 생각 블록은 끔

## 화면

- `/posttrain/train` — **SFT · DPO · 병합**: LoRA 학습 · 학습한 모델 · 어댑터 병합

## 앞으로 할 일

- GPU 에서 큰 모델

## 상세 문서

- [후학습 — 데이터 · 선별 · LoRA SFT · DPO · 병합 · 학습 전후 평가 · GGUF · 실측](posttrain.md)
- [후학습 (Post-training) 맵](../../../maps/posttrain.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [7a 지식 증류](../../llm/7a-distill/README.md) — LLM 시스템 엔지니어링 맵 · ✅ 구현됨
- [5 파인튜닝](../../llm/5-finetune/README.md) — LLM 시스템 엔지니어링 맵 · ✅ 구현됨

---

← [P2 선별 · 누수 방지](../p2-select/README.md) · [전체 맵](../../../maps/posttrain.md) · [P4 선호 학습 (DPO 등)](../p4-pref/README.md) →
