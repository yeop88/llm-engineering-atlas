# LLM 연동

문서 검색 평가 질문 자동 생성처럼 LLM 이 필요한 기능은 두 종류의 API 를 지원합니다. 둘 다 `httpx` 로 REST API 를 직접 호출하므로 추가 SDK 가 필요 없습니다(`app/services/llm.py`).

| 제공자 | 값 | 대상 |
|---|---|---|
| OpenAI 호환 | `openai` | OpenAI, vLLM, Ollama, LM Studio, LiteLLM 등 `/chat/completions` 를 제공하는 서버 |
| Claude | `anthropic` | Claude API (`/v1/messages`) |

## 설정 (`.env`)

```dotenv
# 비우면 키가 설정된 쪽을 사용 (둘 다 있으면 openai)
LLM_PROVIDER=

# OpenAI 호환
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=
OPENAI_MODEL=

# Claude
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-5-5

LLM_TIMEOUT=120
```

로컬 모델 예시:

| 서버 | OPENAI_BASE_URL | OPENAI_MODEL | 키 |
|---|---|---|---|
| Ollama | `http://localhost:11434/v1` | `qwen3:8b` 등 `ollama pull` 한 이름 | 비움 |
| vLLM | `http://localhost:8000/v1` (앱 포트와 겹치지 않게) | 서빙 중인 모델 이름 | 서버 설정에 따름 |
| LM Studio | `http://localhost:1234/v1` | 로드한 모델 이름 | 비움 |

요청마다 `provider`·`model` 을 넘겨 설정을 덮어쓸 수 있습니다. 키는 API 응답에 노출되지 않습니다.

## 동작

- 429·5xx·과부하(529)·시간 초과는 지수 백오프로 최대 3번 다시 시도하고, 인증 오류 같은 4xx 는 바로 실패합니다.
- JSON 이 필요한 호출은 OpenAI 호환 API 에 `response_format: json_object` 를 보내고, 응답에 코드 블록이나 설명이 섞여 있어도 첫 JSON 객체/배열을 꺼냅니다.
- OpenAI 공식 API 에는 `max_completion_tokens`, 호환 서버에는 `max_tokens` 를 보냅니다.
- 입력·출력 토큰 수와 소요 시간을 함께 돌려줘 비용을 가늠할 수 있습니다.

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/llm/status` | 제공자별 설정 상태와 기본 제공자 (키 값 제외) |
| POST | `/api/llm/test` | 연결 시험 `{"provider"?, "model"?, "prompt"?}` → `{"text", "usage", "seconds", "config"}` |
