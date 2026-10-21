<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 컨텍스트 엔지니어링 맵

맥락 예산 · 배치 → 긴 맥락 vs RAG → 도구 결과 · 기록 압축 → 프롬프트 캐시 → 외부 메모리 → 맥락 오염 방지 — 모델에 무엇을 얼마나 보여 줄지 설계하는 흐름

모델이 수십만 토큰을 받게 됐지만, 길게 넣을수록 비싸고 느리고 중간 내용을 놓칩니다. 이 PC 에서 질문당 시간의 2/3 가 근거 읽기였고, 에이전트는 도구 결과가 쌓여 맥락이 금방 찹니다. 무엇을 · 어떤 순서로 · 얼마나 넣고, 언제 줄이고, 무엇을 캐시할지를 재는 맵입니다.

앱의 **맵 → 컨텍스트 엔지니어링 맵**(`/maps/context`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[맥락 예산 · 배치] → [긴 맥락 vs RAG]
                    ↓
[도구 결과 · 기록 압축] → [프롬프트 캐시] → [외부 메모리]
                    ↓
[맥락 오염 방지]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| CX1 | [맥락 예산 · 배치](../stages/context/cx1-budget/README.md) | ⬜ 예정 | 시스템 · 대화 · 근거 · 도구 결과의 몫과 순서를 정하고 위치별 정답률을 잰다 | [S2 근거 길이](../stages/serving/s2-context/README.md) | — |
| CX2 | [긴 맥락 vs RAG](../stages/context/cx2-long/README.md) | ⬜ 예정 | 문서를 통째로 넣는 것과 검색 근거를 넣는 것을 같은 질문으로 비교한다 | [2 RAG](../stages/llm/2-rag/README.md) | — |
| CX3 | [도구 결과 · 기록 압축](../stages/context/cx3-compact/README.md) | ⬜ 예정 | 오래된 도구 결과 · 대화를 지우거나 요약해 맥락을 비운다 | [C5 대화 압축](../stages/conversation/c5-compress/README.md) · [LR3 체크포인트](../stages/longrun/lr3-state/README.md) | — |
| CX4 | [프롬프트 캐시](../stages/context/cx4-cache/README.md) | ⬜ 예정 | 바뀌지 않는 앞부분을 캐시해 읽기 시간 · 비용을 줄인다 | [S1 캐시](../stages/serving/s1-cache/README.md) | — |
| CX5 | [외부 메모리 · 노트](../stages/context/cx5-memory/README.md) | ⬜ 예정 | 에이전트가 노트에 적어 두고 필요할 때 다시 읽는다 | [C3 대화 메모리](../stages/conversation/c3-memory/README.md) | — |
| CX6 | [맥락 오염 방지](../stages/context/cx6-hygiene/README.md) | ⬜ 예정 | 틀린 중간 결과 · 낡은 정보 · 숨은 지시가 맥락에 남지 않게 한다 | [G1 입력 방어](../stages/guardrails/g1-injection/README.md) | — |

## 설계 원칙

- 읽는 양이 지연이다 — 근거 읽기가 시간의 2/3(서빙 실측)
- 넣은 만큼 쓰지 않는다 — 위치별 정답률을 잰다(중간을 놓침)
- 바뀌지 않는 것을 앞에 — 캐시는 앞부분만 다시 쓴다
- 맥락에 들어간 것은 다음 답의 근거가 된다 — 틀린 것은 지운다

## 예시

장기 실행 보고서 작업 → 시스템 · 템플릿(캐시)을 앞에 → 질문과 가까운 근거를 끝에 → 도구 결과는 세 단계가 지나면 요약만 → 중간 결론은 노트에 적고 필요할 때 읽음 → 틀린 것으로 판정된 단계 결과는 맥락에서 뺌.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md)
