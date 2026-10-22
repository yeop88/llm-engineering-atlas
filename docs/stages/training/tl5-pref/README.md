<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# TL5 · 선호 정렬 (Preference alignment)

**상태: ⬜ 예정** — 선호 쌍(DPO) · 검증 가능한 보상(GRPO)으로 답의 질을 맞춘다

## 원리

선호 정렬은 더 나은 답과 못한 답의 쌍(DPO), 또는 정답 확인이 가능한 과제의 보상(GRPO 등)으로 모델을 원하는 방향으로 미는 학습입니다. RLHF · RLAIF 도 같은 자리입니다.

## 왜 하는가

SFT 만으로는 '틀리지 않게' · '모르면 모른다고' 같은 성질을 잘 배우지 못합니다. 보상 해킹이 생기는지 함께 봐야 합니다.

## 어떻게 (이 앱에서)

- (기반) 선호 학습(P4) · GRPO(RV5)
- (예정) 정렬 방식별 결과를 같은 평가로 한 표에

## 화면

- 아직 테스트 화면이 없습니다. 단계 소개는 앱의 `/stages/tl_pref` 에서 볼 수 있습니다.

## 앞으로 할 일

- 정렬 방식별 결과를 같은 평가로 한 표에

## 상세 문서

- [학습 생애주기 맵](../../../maps/training.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [P4 선호 학습 (DPO 등)](../../posttrain/p4-pref/README.md) — 후학습 (Post-training) 맵 · ✅ 구현됨
- [RV5 정책 학습 (GRPO · PPO)](../../rlvr/rv5-policy/README.md) — 강화학습 기반 에이전트 학습 (RLVR) 맵 · ✅ 구현됨

---

← [TL4 지시 튜닝](../tl4-sft/README.md) · [전체 맵](../../../maps/training.md) · [TL6 안전 정렬](../tl6-safety/README.md) →
