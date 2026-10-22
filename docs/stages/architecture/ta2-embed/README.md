<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# TA2 · 임베딩 · 층별 임베딩 (Embeddings)

**상태: ✅ 구현됨** — 어휘 × 차원 표, 출력과 같이 쓰는지, 층별 임베딩이 있는지를 본다

## 원리

임베딩 표는 어휘 수 × 은닉 차원 크기입니다. 출력층과 같은 표를 쓰면(tied) 메모리가 줄고, 층마다 따로 붙이는 임베딩(gemma-4 의 per-layer)은 크지만 토큰마다 한 줄만 읽습니다.

## 왜 하는가

임베딩 표는 '크지만 거의 안 읽는' 가중치라 메모리 계획과 속도 계획에서 다르게 다뤄야 합니다. 같이 세면 속도 어림이 틀립니다.

## 어떻게 (이 앱에서)

- (기반) 임베딩 공간(IP1) · GGUF 텐서 종류(BM1)
- 임베딩 표(층별 임베딩 포함)가 가중치에서 차지하는 몫 — 메모리에는 다 들지만 토큰마다 한 줄만 읽으므로 '토큰마다 읽는 양'에서는 뺀다

## 화면

- `/architecture/layers` — **층 구조 · 비용**: 층별 어텐션 · KV · FFN · 읽는 양 · 맥락 실측

## 상세 문서

- [Transformer · MoE 구조 — 층별 어텐션 종류 · KV · FFN/전문가 · 읽는 양 · 맥락 길이별 실측](../ta1-tokenize/architecture.md)
- [Transformer · MoE 구조 맵](../../../maps/architecture.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [IP1 임베딩 공간 분석](../../interp/ip1-space/README.md) — 해석 가능성 · 모델 내부 맵 · ✅ 구현됨

---

← [TA1 토큰화](../ta1-tokenize/README.md) · [전체 맵](../../../maps/architecture.md) · [TA3 어텐션 종류](../ta3-attention/README.md) →
