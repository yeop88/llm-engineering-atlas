<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 프롬프트 · KV 캐시 압축 맵

토큰 단위 프롬프트 압축 → 질문을 아는 압축 → 주의 싱크 + 최근 창 → 중요 토큰 KV 남기기 → KV 양자화 → 압축률 vs 품질 평가 — 같은 모델로 더 긴 맥락을 싸게

근거 읽기가 지연의 2/3 였습니다. 같은 근거를 더 적은 토큰으로 넣거나(프롬프트 압축), 읽은 뒤의 KV 캐시를 줄이면(KV 압축) 같은 모델로 더 긴 맥락을 싸게 다룰 수 있습니다. 작은 공개 모델로 토큰마다 정보량을 재고 KV 를 직접 잘라 보며, 압축률마다 정답률이 얼마나 떨어지는지 잽니다.

앱의 **맵 → 프롬프트 · KV 캐시 압축 맵**(`/maps/compress`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[토큰 단위 압축] → [질문을 아는 압축]
                    ↓
[주의 싱크 + 최근 창] → [중요 토큰 KV]
                    ↓
[KV 양자화] → [압축 평가]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| KC1 | [토큰 단위 프롬프트 압축](../stages/compress/kc1-token/README.md) | ⬜ 예정 | 작은 모델이 쉽게 맞히는(정보가 적은) 토큰을 지워 근거를 줄인다 | [S2 근거 길이](../stages/serving/s2-context/README.md) | — |
| KC2 | [질문을 아는 압축](../stages/compress/kc2-query/README.md) | ⬜ 예정 | 질문에 비춰 관계없는 문장은 통째로, 남은 문장은 토큰 단위로 줄인다 | [KC1 토큰 압축](../stages/compress/kc1-token/README.md) · [CX1 맥락 배치](../stages/context/cx1-budget/README.md) | — |
| KC3 | [주의 싱크 + 최근 창](../stages/compress/kc3-sink/README.md) | ⬜ 예정 | 첫 몇 토큰과 최근 창만 KV 에 남겨 끝없이 긴 대화를 고정 메모리로 돈다 | [IP2 근거 기여](../stages/interp/ip2-attribution/README.md) | — |
| KC4 | [중요 토큰 KV 남기기](../stages/compress/kc4-heavy/README.md) | ⬜ 예정 | 주의를 많이 받은 토큰의 KV 만 남겨 캐시를 줄인다 | [KC3 주의 싱크](../stages/compress/kc3-sink/README.md) | — |
| KC5 | [KV 양자화](../stages/compress/kc5-kvquant/README.md) | ⬜ 예정 | KV 캐시를 8 · 4비트로 저장해 같은 메모리에 더 긴 맥락을 둔다 | [S5 디코딩 최적화](../stages/serving/s5-decode/README.md) · [7b 양자화](../stages/llm/7b-quant/README.md) | — |
| KC6 | [압축 평가](../stages/compress/kc6-eval/README.md) | ⬜ 예정 | 압축률마다 같은 질문의 정답률 · 지연 · 남은 숫자 · 조항을 잰다 | [E2 회귀 평가](../stages/evalops/e2-offline/README.md) | — |

## 설계 원칙

- 읽는 양이 지연이다 — 근거 읽기가 시간의 2/3(서빙 실측)
- 정보가 적은 토큰부터 뺀다 — 작은 모델이 쉽게 맞히는 토큰은 큰 모델도 안다
- 첫 토큰은 남긴다 — 주의가 몰리는 자리(주의 싱크)를 지우면 무너진다
- 압축률마다 같은 질문으로 — 숫자 · 조항이 사라지는지 본다

## 예시

근거 6,000자 → 작은 모델이 쉽게 맞히는 조사 · 반복 토큰을 빼 2,400자로(질문과 관계없는 문장은 통째로) → 답 근거의 조문 번호 · 숫자는 남았는지 검사 → 긴 대화는 첫 4토큰 + 최근 창만 KV 에 두고 → KV 를 8비트로 저장해 메모리 절반.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md)
