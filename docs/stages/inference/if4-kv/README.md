<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# IF4 · KV 캐시 관리 (KV cache management)

**상태: ✅ 구현됨** — KV 형식 · 블록 · 자르기를 워크로드에 맞춰 고른다

## 원리

KV 캐시 관리는 KV 의 비트(f16 · q8_0 · q4_0), 블록 단위 할당(페이지), 자르기 정책(싱크 · 중요 토큰)을 고르는 것입니다. 긴 맥락 · 많은 동시 요청일수록 KV 가 메모리의 대부분이 됩니다.

## 왜 하는가

KV 를 줄이면 같은 메모리에 더 많은 요청 · 더 긴 맥락이 들어가지만, 정책마다 품질 손실이 다릅니다.

## 어떻게 (이 앱에서)

- (기반) KV 양자화(KC5) · 페이지 KV(BM4)
- KV q8_0 · q4_0 칸(같은 묶음 중 먼저 통과한 하나만 남김) — 서버가 적은 KV 크기와 함께

## 화면

- `/inference/ladder#ladder` — **KV 캐시 칸**: KV q8_0 · q4_0

## 상세 문서

- [추론 최적화 — 워크로드 · 미리 채우기 · 생성 분리 · 최적화 사다리 · 품질 게이트 · 실측](../if1-measure/inference.md)
- [추론 최적화 맵](../../../maps/inference.md)

## 기반 단계

이미 있는 단계 위에 짓습니다.

- [KC5 KV 양자화](../../compress/kc5-kvquant/README.md) — 프롬프트 · KV 캐시 압축 맵 · ✅ 구현됨
- [BM4 페이지 KV 캐시](../../bigmodel/bm4-paged/README.md) — 적은 메모리로 큰 모델 돌리기 맵 · ✅ 구현됨

---

← [IF3 양자화](../if3-quant/README.md) · [전체 맵](../../../maps/inference.md) · [IF5 연속 배칭](../if5-batch/README.md) →
