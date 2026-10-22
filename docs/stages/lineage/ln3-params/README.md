<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# LN3 · 파라미터 · MoE 구조 (Parameters & MoE)

**상태: ⬜ 예정** — 전체 · 활성 파라미터, 밀집 · MoE, 층 · 차원을 설정 파일에서 읽는다

## 원리

파라미터 구조는 전체 파라미터와 토큰마다 쓰는 활성 파라미터, 층 수 · 은닉 차원 · KV 머리 수 · 전문가 수 같은 숫자입니다. 메모리와 속도를 정하는 것은 이름의 '30B' 보다 이 숫자들입니다.

## 왜 하는가

같은 30B 도 밀집이면 토큰마다 30B 를 읽고, MoE 면 3B 만 읽습니다. 이 차이를 모르면 메모리 계획과 속도 예상이 몇 배 틀립니다.

## 어떻게 (이 앱에서)

- (기반) 메모리 계획(BM1, config · GGUF 읽기)
- (예정) config 에서 전체 · 활성 파라미터 계산 · 구조 노드 · HAS_ARCHITECTURE

## 화면

- 아직 테스트 화면이 없습니다. 단계 소개는 앱의 `/stages/ln_params` 에서 볼 수 있습니다.

## 앞으로 할 일

- config 에서 전체 · 활성 파라미터 계산 · 구조 노드 · HAS_ARCHITECTURE

## 상세 문서

- [기반 모델 계보 맵](../../../maps/lineage.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [BM1 메모리 계획](../../bigmodel/bm1-plan/README.md) — 적은 메모리로 큰 모델 돌리기 맵 · ✅ 구현됨
- [IP1 임베딩 공간 분석](../../interp/ip1-space/README.md) — 해석 가능성 · 모델 내부 맵 · ✅ 구현됨

---

← [LN2 모델 세대](../ln2-generation/README.md) · [전체 맵](../../../maps/lineage.md) · [LN4 컨텍스트 길이](../ln4-context/README.md) →
