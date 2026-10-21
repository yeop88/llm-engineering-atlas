<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 엔터프라이즈 AI 플랫폼 아키텍처 맵

게이트웨이 → 멀티테넌트 격리 → 모델 · 프롬프트 레지스트리 → 설정 · 기능 플래그 → 배포 → 장애 대응 · 대체 모델 → 비용 배분 — 맵들을 실제 운영 시스템으로 묶는 흐름

여러 부서 · 고객사가 같은 AI 시스템을 쓰기 시작하면, 기술보다 운영의 경계가 핵심이 됩니다 — 누가 어떤 자료를 보고, 누가 모델 · 프롬프트를 바꾸고, 장애 때 무엇으로 대체하며, 비용을 누가 내는가. 이 맵은 앞의 맵들(검색 · 에이전트 · 가드레일 · 서빙)을 하나의 플랫폼으로 운영할 때 필요한 층을 다룹니다.

앱의 **맵 → 엔터프라이즈 AI 플랫폼 아키텍처 맵**(`/maps/platform`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[API 게이트웨이 (인증 · 속도 제한 · 요금)] → [멀티테넌트 격리]
                                      ↓
[모델 · 프롬프트 레지스트리 · 버전] → [설정 · 기능 플래그]
                                      ↓
[배포 · 단계적 출시] → [장애 대응 · 대체 모델] → [비용 배분 · 사용량 보고]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| PF1 | [API 게이트웨이](../stages/platform/pf1-gateway/README.md) | ✅ 구현됨 | 모든 요청이 들어오는 입구에서 인증 · 테넌트 구분 · 속도 제한 · 사용량 기록을 한다 | [G5 감사 로그](../stages/guardrails/g5-audit/README.md) | [엔터프라이즈 AI 플랫폼 — 게이트웨이 · 테넌트 · 프롬프트 · 플래그 · 장애 대응 · 비용 · 실측](../stages/platform/pf1-gateway/platform.md) |
| PF2 | [멀티테넌트 격리](../stages/platform/pf2-tenancy/README.md) | ✅ 구현됨 | 부서 · 고객사마다 자료 · 색인 · 설정 · 로그를 분리해 서로 보이지 않게 한다 | [G3 권한별 검색](../stages/guardrails/g3-acl/README.md) | [엔터프라이즈 AI 플랫폼 — 게이트웨이 · 테넌트 · 프롬프트 · 플래그 · 장애 대응 · 비용 · 실측](../stages/platform/pf1-gateway/platform.md) |
| PF3 | [모델 · 프롬프트 레지스트리 · 버전](../stages/platform/pf3-registry/README.md) | ✅ 구현됨 | 모델 · 프롬프트 · 검색 설정을 버전으로 저장하고, 어느 답이 어느 버전에서 나왔는지 남긴다 | [1 임베딩](../stages/llm/1-embedding/README.md) | [엔터프라이즈 AI 플랫폼 — 게이트웨이 · 테넌트 · 프롬프트 · 플래그 · 장애 대응 · 비용 · 실측](../stages/platform/pf1-gateway/platform.md) |
| PF4 | [설정 · 기능 플래그](../stages/platform/pf4-config/README.md) | ✅ 구현됨 | 테넌트 · 사용자 묶음별로 다른 설정을 켜고 끄며, 코드 배포 없이 동작을 바꾼다 | [6 라우팅](../stages/llm/6-routing/README.md) | [엔터프라이즈 AI 플랫폼 — 게이트웨이 · 테넌트 · 프롬프트 · 플래그 · 장애 대응 · 비용 · 실측](../stages/platform/pf1-gateway/platform.md) |
| PF5 | [배포 · 단계적 출시](../stages/platform/pf5-deploy/README.md) | ✅ 구현됨 | 컨테이너로 배포하고, 버전 · 마이그레이션 · 릴리스 노트 규칙을 지킨다 | [S4 추론 서버](../stages/serving/s4-server/README.md) | [엔터프라이즈 AI 플랫폼 — 게이트웨이 · 테넌트 · 프롬프트 · 플래그 · 장애 대응 · 비용 · 실측](../stages/platform/pf1-gateway/platform.md) |
| PF6 | [장애 대응 · 대체 모델](../stages/platform/pf6-resilience/README.md) | ✅ 구현됨 | 모델 서버 · 벡터 DB · 외부 API 가 멈추면 대체 경로로 넘어가고, 품질 차이를 알린다 | [S4 추론 서버](../stages/serving/s4-server/README.md) · [6 라우팅](../stages/llm/6-routing/README.md) | [엔터프라이즈 AI 플랫폼 — 게이트웨이 · 테넌트 · 프롬프트 · 플래그 · 장애 대응 · 비용 · 실측](../stages/platform/pf1-gateway/platform.md) |
| PF7 | [비용 배분 · 사용량 보고](../stages/platform/pf7-chargeback/README.md) | ✅ 구현됨 | 테넌트 · 기능별 사용량과 비용을 집계해 배분하고, 예산을 넘기 전에 알린다 | [E4 비용 · 지연](../stages/evalops/e4-cost/README.md) | [엔터프라이즈 AI 플랫폼 — 게이트웨이 · 테넌트 · 프롬프트 · 플래그 · 장애 대응 · 비용 · 실측](../stages/platform/pf1-gateway/platform.md) |

## 설계 원칙

- 격리는 데이터 단에서 — 테넌트 필터를 화면에서만 걸면 API 로 샌다(권한별 검색 원칙과 같음)
- 바꿀 수 있는 것은 모두 버전으로 — 모델 · 프롬프트 · 청킹 설정이 바뀌면 같은 질문의 답이 바뀐다(답변 규칙 5번 추가로 답 길이가 바뀐 것처럼)
- 대체 경로를 미리 잰다 — 큰 모델이 멈추면 소형 모델로 가되, 품질 차이(E2B −13)를 알고 있어야 한다
- 호환성은 업그레이드 때 자동으로 — 라이브러리 버전이 바뀌면 모델 호환성 점검(모델 화면)

## 예시

법무팀과 고객센터가 같은 플랫폼을 씀: 게이트웨이가 토큰으로 테넌트를 구분 → 법무팀 질문은 법률 컬렉션 · 법률 프롬프트 v3, 고객센터는 AS 매뉴얼 · 상담 프롬프트 v7 → 새 프롬프트는 기능 플래그로 고객센터 10% 에만 → 로컬 LLM 장애 시 클라우드 API 로 대체 · 사용량은 팀별로 집계.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md)
