<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# TA3 · 어텐션 종류 (Attention variants)

**상태: ✅ 구현됨** — 전체 · GQA · 슬라이딩 창 · 선형 어텐션 · 상태 공간 층의 KV 와 연산을 비교한다

## 원리

어텐션은 전체(모든 앞 토큰), 그룹 쿼리(KV 머리를 나눠 씀), 슬라이딩 창(최근 n 토큰만), 선형 어텐션 · 상태 공간(고정 크기 상태)으로 나뉩니다. 층마다 섞어 쓰는 하이브리드 모델이 늘었습니다.

## 왜 하는가

긴 맥락의 메모리는 대부분 KV 입니다. 층 종류를 모르고 '층 수 × 맥락' 으로 세면 하이브리드 모델의 KV 를 몇 배 크게 잡습니다.

## 어떻게 (이 앱에서)

- (기반) 층별 KV 계산(BM1) · 주의 싱크(KC3)
- 층마다 어텐션 종류(전체 · 슬라이딩 창 · 앞 층 KV 공유 · 선형 상태) · KV 차원, 맥락 길이별 KV 를 '층 수 × 맥락' 어림과 나란히
- 작은 공개 LM 으로 길이를 두 배씩 늘려 미리 채우기 시간 배율 · 캐시의 실제 KV 텐서 크기를 잰다

## 화면

- `/architecture/layers#layers` — **어텐션 종류**: 층마다 전체 · 슬라이딩 창 · KV 공유 · 선형 상태
- `/architecture/layers#scaling` — **맥락 길이별 실측**: 미리 채우기 시간 · 실제 KV

## 상세 문서

- [Transformer · MoE 구조 — 층별 어텐션 종류 · KV · FFN/전문가 · 읽는 양 · 맥락 길이별 실측](../ta1-tokenize/architecture.md)
- [Transformer · MoE 구조 맵](../../../maps/architecture.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [BM1 메모리 계획](../../bigmodel/bm1-plan/README.md) — 적은 메모리로 큰 모델 돌리기 맵 · ✅ 구현됨
- [KC3 주의 싱크 + 최근 창](../../compress/kc3-sink/README.md) — 프롬프트 · KV 캐시 압축 맵 · ✅ 구현됨

---

← [TA2 임베딩 · 층별 임베딩](../ta2-embed/README.md) · [전체 맵](../../../maps/architecture.md) · [TA4 FFN · 전문가](../ta4-ffn/README.md) →
