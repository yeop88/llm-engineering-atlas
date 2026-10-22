<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# TK5 · 위치 표현 (Positional encoding)

**상태: ✅ 구현됨** — 회전 위치 부호(RoPE) · 확장 방식이 긴 맥락에 주는 영향을 본다

## 원리

위치 표현은 토큰 순서를 모델에 알리는 방식입니다. 요즘 모델은 대부분 회전 위치 부호를 쓰고, 학습 길이보다 길게 쓰려고 주파수를 늘립니다(YaRN 등). 슬라이딩 창 층은 다른 주파수를 쓰기도 합니다.

## 왜 하는가

KV 를 자를 때(KC3) 위치를 지켜야 하는 이유, 긴 맥락에서 중간을 놓치는 이유가 위치 표현에 있습니다.

## 어떻게 (이 앱에서)

- (기반) KV 자르기(KC3) · 컨텍스트 길이(LN4)
- config 의 rope θ · 확장(rope_scaling) · 최대 위치

## 화면

- `/tokenizer/compare#compare` — **위치 표현**: 회전 위치 θ · 확장 · 최대 길이

## 상세 문서

- [토크나이저 · 표현 공간 — 글 종류별 토큰 효율 · 표시 쪼개짐 · 어휘 · 정규화 · 임베딩 · 위치 · 이미지 토큰 · 실측](../tk1-normalize/tokenizer.md)
- [토크나이저 · 표현 공간 맵](../../../maps/tokenizer.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [LN4 컨텍스트 길이](../../lineage/ln4-context/README.md) — 기반 모델 계보 맵 · ✅ 구현됨

---

← [TK4 임베딩 표현](../tk4-embed/README.md) · [전체 맵](../../../maps/tokenizer.md) · [TK6 멀티모달 공통 공간](../tk6-multimodal/README.md) →
