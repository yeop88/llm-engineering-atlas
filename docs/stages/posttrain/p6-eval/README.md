<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# P6 · 후학습 평가 · 안전성 (Post-training evaluation)

**상태: ✅ 구현됨** — 학습 전후를 같은 평가 세트 · 같은 조건으로 비교하고, 안전성 회귀가 없는지 본다

## 원리

후학습은 목표한 능력을 올리면서 다른 능력 · 안전성을 떨어뜨릴 수 있습니다(망각). 도메인 평가 세트 · 일반 능력 · 레드팀 세트를 함께 다시 잽니다.

## 왜 하는가

학습 효과는 같은 조건의 비교로만 확인할 수 있습니다 — 파인튜닝 실측에서 작은 데이터 · 높은 학습률은 오히려 나빠졌습니다.

## 어떻게 (이 앱에서)

- 학습한 모델을 앱 안의 OpenAI 호환 끝점(/api/posttrain/v1, pt-base · pt-번호)으로 올려 LLM 비교(7b)와 같은 질문 · 같은 근거 · 같은 채점, 같은 공격 문항(레드팀 G7)으로 학습 전후 비교 — 첫 모델이 기준(짝 비교)
- 품질이 올라도 안전성(공격 방어 · 정상 통과)이 떨어지면 쓰지 않는다

## 화면

- `/posttrain/eval` — **학습 전후 평가 · GGUF**: 같은 조건 품질 · 안전성 비교 · 변환

## 상세 문서

- [후학습 — 데이터 · 선별 · LoRA SFT · DPO · 병합 · 학습 전후 평가 · GGUF · 실측](../p3-sft/posttrain.md)
- [후학습 (Post-training) 맵](../../../maps/posttrain.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [2 RAG 검색](../../llm/2-rag/README.md) — LLM 시스템 엔지니어링 맵 · ✅ 구현됨
- [E2 오프라인 평가 · 회귀](../../evalops/e2-offline/README.md) — 평가 · 관측 (LLMOps) 맵 · ✅ 구현됨
- [G7 레드팀 · 안전성 평가](../../guardrails/g7-redteam/README.md) — 보안 · 가드레일 · 거버넌스 맵 · ✅ 구현됨

---

← [P5 어댑터 (LoRA) · 모델 병합](../p5-adapter/README.md) · [전체 맵](../../../maps/posttrain.md) · [P7 배포 형식 변환 (GGUF · 양자화)](../p7-export/README.md) →
