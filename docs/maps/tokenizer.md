<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->

# 토크나이저 · 표현 공간 맵

원문 정규화 → 토큰 분할 → 어휘 → 임베딩 → 위치 표현 → 멀티모달 공통 공간 — 한국어 토큰 효율 · 코드 · 이미지 패치 · 오디오 토큰

한국어는 같은 뜻에 영어보다 토큰을 많이 쓰는 모델이 많습니다. 토큰 수는 맥락 · 비용 · 지연을 모두 곱합니다. 모델마다 같은 한국어 · 코드 · 법령 글을 넣어 토큰 효율과 쪼개지는 모양을 재고, 임베딩 · 위치 표현 · 멀티모달 공간이 어떻게 한곳에 모이는지 봅니다.

앱의 **맵 → 토크나이저 · 표현 공간 맵**(`/maps/tokenizer`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. **기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.

## 전체 흐름

```
[정규화] → [토큰 분할] → [어휘]
                    ↓
[임베딩] → [위치 표현] → [멀티모달 공통 공간]
```

## 단계

| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |
|---|---|---|---|---|---|
| TK1 | [원문 정규화](../stages/tokenizer/tk1-normalize/README.md) | ✅ 구현됨 | 유니코드 정규화 · 공백 · 전각 문자를 토크나이저 앞에서 맞춘다 | [D4 정제 · 중복](../stages/docintel/d4-clean/README.md) | [토크나이저 · 표현 공간 — 글 종류별 토큰 효율 · 표시 쪼개짐 · 어휘 · 정규화 · 임베딩 · 위치 · 이미지 토큰 · 실측](../stages/tokenizer/tk1-normalize/tokenizer.md) |
| TK2 | [토큰 분할](../stages/tokenizer/tk2-split/README.md) | ✅ 구현됨 | 한국어 · 영어 · 코드 · 조문 번호의 글자당 토큰과 쪼개지는 모양을 모델별로 잰다 | [IP1 임베딩 공간](../stages/interp/ip1-space/README.md) | [토크나이저 · 표현 공간 — 글 종류별 토큰 효율 · 표시 쪼개짐 · 어휘 · 정규화 · 임베딩 · 위치 · 이미지 토큰 · 실측](../stages/tokenizer/tk1-normalize/tokenizer.md) |
| TK3 | [어휘](../stages/tokenizer/tk3-vocab/README.md) | ✅ 구현됨 | 어휘 크기 · 언어별 몫 · 특수 토큰을 본다 | [TK2 토큰 분할](../stages/tokenizer/tk2-split/README.md) | [토크나이저 · 표현 공간 — 글 종류별 토큰 효율 · 표시 쪼개짐 · 어휘 · 정규화 · 임베딩 · 위치 · 이미지 토큰 · 실측](../stages/tokenizer/tk1-normalize/tokenizer.md) |
| TK4 | [임베딩 표현](../stages/tokenizer/tk4-embed/README.md) | ✅ 구현됨 | 토큰 · 문장 임베딩 공간의 비등방성 · 언어 간 정렬을 잰다 | [IP1 임베딩 공간](../stages/interp/ip1-space/README.md) | [토크나이저 · 표현 공간 — 글 종류별 토큰 효율 · 표시 쪼개짐 · 어휘 · 정규화 · 임베딩 · 위치 · 이미지 토큰 · 실측](../stages/tokenizer/tk1-normalize/tokenizer.md) |
| TK5 | [위치 표현](../stages/tokenizer/tk5-position/README.md) | ✅ 구현됨 | 회전 위치 부호(RoPE) · 확장 방식이 긴 맥락에 주는 영향을 본다 | [LN4 컨텍스트](../stages/lineage/ln4-context/README.md) | [토크나이저 · 표현 공간 — 글 종류별 토큰 효율 · 표시 쪼개짐 · 어휘 · 정규화 · 임베딩 · 위치 · 이미지 토큰 · 실측](../stages/tokenizer/tk1-normalize/tokenizer.md) |
| TK6 | [멀티모달 공통 공간](../stages/tokenizer/tk6-multimodal/README.md) | ✅ 구현됨 | 이미지 패치 · 오디오 토큰 · 영상 시공간 토큰이 글과 한 공간에 놓이는 방식 | [MA1 멀티모달 임베딩](../stages/multi-agent/ma1-input/README.md) | [토크나이저 · 표현 공간 — 글 종류별 토큰 효율 · 표시 쪼개짐 · 어휘 · 정규화 · 임베딩 · 위치 · 이미지 토큰 · 실측](../stages/tokenizer/tk1-normalize/tokenizer.md) |

## 설계 원칙

- 토큰 수가 비용 단위다 — 글자당 토큰을 모델마다 잰다
- 쪼개지는 모양이 품질이다 — 코드 · 조문 번호가 어떻게 나뉘나
- 공간은 비교로 — 같은 뜻의 한국어 · 영어 · 이미지가 가까운가

## 예시

같은 법령 1,000자 → 모델 A 520 토큰 · 모델 B 780 토큰 → B 는 같은 근거로 맥락 1.5 배 · 미리 채우기 1.5 배 → 'E4' · '제3조의2' 가 몇 토큰으로 나뉘는지 보고 압축 보호(KC1) 규칙에 반영.

---

다른 맵: [LLM 시스템 엔지니어링 맵](llm.md) · [지식 그래프 · GraphRAG 맵](knowledge-graph.md) · [멀티에이전트 · 멀티모달 맵](multi-agent.md) · [평가 · 관측 (LLMOps) 맵](evalops.md) · [보안 · 가드레일 · 거버넌스 맵](guardrails.md) · [문서 처리 (Document Intelligence) 맵](docintel.md) · [서빙 · 추론 최적화 · 비용 맵](serving.md) · [대화 · 메모리 맵](conversation.md) · [서비스 시나리오: 고객 AS 상담 맵](as-service.md) · [후학습 (Post-training) 맵](posttrain.md) · [데이터 플라이휠 맵](flywheel.md) · [엔터프라이즈 AI 플랫폼 아키텍처 맵](platform.md) · [에이전트 상호운용 · 도구 생태계 맵 (MCP · A2A)](interop.md) · [실시간 음성 상담 맵](voice.md) · [규제 대응 · 컴플라이언스 맵](compliance.md) · [장기 실행 에이전트 · 업무 자동화 맵](longrun.md) · [강화학습 기반 에이전트 학습 (RLVR) 맵](rlvr.md) · [온디바이스 · 엣지 맵](edge.md) · [추론 모델 · 테스트 시간 연산 맵](reasoning.md) · [컨텍스트 엔지니어링 맵](context.md) · [데이터 분석 에이전트 · Text-to-SQL 맵](analytics.md) · [코딩 에이전트 · 소프트웨어 엔지니어링 맵](coding.md) · [컴퓨터 사용 · 브라우저 에이전트 맵](computer-use.md) · [해석 가능성 · 모델 내부 맵](interp.md) · [장기 메모리 · 메모리 DB 맵](memory.md) · [프롬프트 · KV 캐시 압축 맵](compress.md) · [옴니채널 · 실시간 멀티모달 에이전트 맵](omni.md) · [적은 메모리로 큰 모델 돌리기 맵](bigmodel.md) · [기반 모델 계보 맵](lineage.md) · [Transformer · MoE 구조 맵](architecture.md) · [학습 생애주기 맵](training.md) · [데이터 계보 · 근거 맵](provenance.md) · [개인화 · 적응 맵](personalize.md) · [에이전트 경제 · 거래 맵](economy.md) · [실시간 스트리밍 LLM 맵](realtime.md) · [오디오 이해 맵](audio.md) · [이미지 · Vision-Language 맵](vision.md) · [비디오 이해 맵](video.md) · [실시간 오디오 · 비디오 풀듀플렉스 맵](duplex.md) · [생성 이미지 · 비디오 제작 맵](genmedia.md) · [추론 최적화 맵](inference.md) · [모델 라우팅 · 비용 최적화 맵](routing.md) · [합성 데이터 맵](synthetic.md)
