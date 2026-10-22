<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# TL4 · 지시 튜닝 (Instruction tuning)

**상태: ✅ 구현됨** — 지시 · 답 쌍으로 LoRA SFT — 무엇을 배웠고 무엇을 잃었나

## 원리

지시 튜닝은 지시와 좋은 답의 쌍으로 모델이 지시를 따르게 하는 학습입니다. 이 앱은 LoRA 로 하고, 배운 업무 정답률과 함께 잃은 일반 능력(망각)을 잽니다.

## 왜 하는가

튜닝으로 한 업무가 좋아지면서 다른 것이 나빠지는 일이 흔합니다. 둘을 같이 재야 배포를 정합니다.

## 어떻게 (이 앱에서)

- (기반) LoRA SFT(P3)
- 만든 순서의 SFT 어댑터 · 학습 건수 · 마지막 손실

## 화면

- `/training/lifecycle#lifecycle` — **지시 튜닝**: SFT 어댑터 · 건수 · 손실

## 상세 문서

- [학습 생애주기 — 모델 원장(데이터 → 거르기 → 기본 모델 → SFT → 선호 정렬 → 안전 → 평가 → 배포) · 학습 데이터 감사](../tl1-collect/training.md)
- [학습 생애주기 맵](../../../maps/training.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [P3 SFT (지도 미세조정)](../../posttrain/p3-sft/README.md) — 후학습 (Post-training) 맵 · ✅ 구현됨

---

← [TL3 사전학습](../tl3-pretrain/README.md) · [전체 맵](../../../maps/training.md) · [TL5 선호 정렬](../tl5-pref/README.md) →
