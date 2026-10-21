<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# S6 · 하드웨어 배치 (Hardware placement)

**상태: ✅ 구현됨** — 어느 모델을 CPU · 내장 GPU · 외장 GPU 에 둘지, 몇 개를 올려 둘지 정한다

## 원리

임베딩 · 리랭커 · LLM 은 계산 특성이 달라 놓을 자리가 다릅니다. 메모리에 올려 둘 모델 수, 장치별 속도, 동시 요청을 고려해 배치를 정합니다.

## 왜 하는가

이 PC 에서 CPU 리랭커는 질문당 12~48초였고 LLM 은 내장 GPU(Vulkan)에서 돌았습니다. 같은 구성이라도 장치 배치에 따라 병목이 달라집니다.

## 어떻게 (이 앱에서)

- (있음) CPU · CUDA · ROCm 설치 가이드, 모델 LRU 로드(MAX_LOADED_MODELS), bf16/fp32 자동 선택
- 지금 쓰는 장치 · 빌드 · 올라간 임베딩 · 리랭커(장치 · dtype · 로드 시간) · 메모리 사용을 한 화면에

## 화면

- `/serving/budget#resources` — **하드웨어 배치**: 장치 · 올라간 모델 · 메모리

## 앞으로 할 일

- 장치별 단계 지연 표

## 상세 문서

- [서빙 · 추론 최적화 — 동시 부하 · KV 캐시 · 추측 디코딩 · 예산 · 자원 · 실측](../s4-server/serving.md)
- [서빙 · 추론 최적화 · 비용 맵](../../../maps/serving.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [1 데이터 임베딩](../../llm/1-embedding/README.md) — LLM 시스템 엔지니어링 맵 · ✅ 구현됨

---

← [S5 KV 캐시 · 추측 디코딩](../s5-decode/README.md) · [전체 맵](../../../maps/serving.md) · [S7 비용 · 지연 예산](../s7-budget/README.md) →
