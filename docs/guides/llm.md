# LLM 연동

문서 검색 평가 질문 자동 생성처럼 LLM 이 필요한 기능은 두 종류의 API 를 지원합니다. 둘 다 `httpx` 로 REST API 를 직접 호출하므로 추가 SDK 가 필요 없습니다(`app/core/llm.py`).

| 제공자 | 값 | 대상 |
|---|---|---|
| OpenAI 호환 | `openai` | OpenAI, vLLM, Ollama, LM Studio, LiteLLM 등 `/chat/completions` 를 제공하는 서버 |
| Claude | `anthropic` | Claude API (`/v1/messages`) |

## 로컬 LLM (권장 구성)

가장 가벼운 실행기는 [llama.cpp](https://github.com/ggml-org/llama.cpp/releases) 의 `llama-server` 입니다. 설치 없이 압축만 풀면 되고(Vulkan 빌드 32MB), OpenAI 호환 API 를 제공합니다. Ollama 는 설치형 백그라운드 서비스라 더 무겁습니다.

| 그래픽 | 받을 파일 |
|---|---|
| AMD·Intel 내장/외장 GPU | `llama-bXXXX-bin-win-vulkan-x64.zip` |
| NVIDIA | `llama-bXXXX-bin-win-cuda-13.x-x64.zip` (+ `cudart-…` 런타임) |
| GPU 없음 | `llama-bXXXX-bin-win-cpu-x64.zip` |

```powershell
# 예: 안정 릴리스 v0.7.0(b11669) Vulkan 빌드를 C:\Users\<사용자>\llama.cpp 에 풀고
llama-server.exe --list-devices          # GPU 가 잡히는지 확인
llama-server.exe -m C:\Users\<사용자>\llm-models\gemma-4-E4B_q4_0-it.gguf --host 127.0.0.1 --port 8081 -c 16384 -ngl 99 -np 2 --alias gemma-4-e4b
```

```dotenv
OPENAI_BASE_URL=http://127.0.0.1:8081/v1
OPENAI_MODEL=gemma-4-e4b
```

- `-ngl 99`: 모든 층을 GPU 에 올림 (내장 GPU 는 시스템 메모리를 공유). `-c`: 문맥 길이(근거를 많이 넣으려면 크게). `-np 2`: 동시 요청 수. `--alias`: API 에서 쓸 모델 이름.
- 모델 파일(GGUF)은 Hugging Face 에서 받습니다. 받은 뒤 Hub 의 SHA-256 과 대조하세요.
- Qwen3 계열처럼 '생각(thinking)' 모드가 있는 모델은 앱이 생각을 끄라고 요청합니다(`LLM_DISABLE_THINKING=true`, 기본). 응답에 `<think>` 가 섞여 와도 걸러냅니다.

### 소형 모델 비교 (2026-10, 이 프로젝트 개발 PC)

Ryzen 7 7735U · Radeon 680M(Vulkan, 공유 메모리) · RAM 28GB, 모두 4비트 GGUF. 공공문서 지문 6개로 평가 질문 생성(유형 3개 × 6 = 18개 기대), 정답을 아는 근거 인용 질문 4개.

| 모델 | 파일 | 질문 생성 | 근거 원문 그대로 | 근거 답변 정답 | 올바른 인용 | 속도 |
|---|---|---|---|---|---|---|
| **Gemma 4 E4B** (Google 공식 QAT q4_0, Apache-2.0) | 5.2GB | 18/18 | **18/18** | 3/4 | 3/4 | 7.9 토큰/초 |
| Qwen3.5-4B (unsloth Q4_K_M, Apache-2.0) | 2.7GB | 18/18 | 14/18 | **4/4** | **4/4** | 8.3 토큰/초 |
| Kanana 2 3B (mradermacher Q4_K_M, kanana 라이선스) | 2.2GB | 3/18 (영어 질문·빈 응답) | 0/3 | 2/4 | 0/4 | 10.8 토큰/초 |

- **기본값은 Gemma 4 E4B** 입니다. 이 앱에서 LLM 을 가장 많이 쓰는 질문 생성(평가 세트·파인튜닝 데이터)에서 한국어가 가장 자연스럽고, 근거 문장을 모두 원문 그대로 옮겼습니다. 놓친 1문항은 지어내지 않고 "근거에서 찾을 수 없습니다"라고 답했습니다.
- Qwen3.5-4B 는 답변 정확도가 가장 좋았지만 숫자 사이에 공백을 넣는 버릇("2 천만 원", "7 월 1 일")과 오타가 있었습니다. 파일이 절반 크기라 메모리가 부족하면 대안으로 쓰세요.
- Kanana 2 3B 는 이 GGUF·llama.cpp 조합에서 지시를 따르지 못했습니다(채팅 템플릿 문제일 수 있음).
- 근거가 2,000토큰쯤이면 첫 글자까지 20초 안팎(근거 읽기)이 걸리고, 그 뒤 생성은 8~12 토큰/초입니다. 답변 화면에 두 시간을 따로 보여 줍니다.

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
LLM_DISABLE_THINKING=true   # 로컬·호환 서버에 생각 모드 끄기 요청 (공식 OpenAI API 에는 보내지 않음)
```

로컬 모델 예시:

| 서버 | OPENAI_BASE_URL | OPENAI_MODEL | 키 |
|---|---|---|---|
| Ollama | `http://localhost:11434/v1` | `qwen3:8b` 등 `ollama pull` 한 이름 | 비움 |
| vLLM | `http://localhost:8000/v1` (앱 포트와 겹치지 않게) | 서빙 중인 모델 이름 | 서버 설정에 따름 |
| LM Studio | `http://localhost:1234/v1` | 로드한 모델 이름 | 비움 |

요청마다 `provider`·`model` 을 넘겨 설정을 덮어쓸 수 있습니다. 키는 API 응답에 노출되지 않습니다.

### 여러 로컬 모델 (모델별 서버 주소)

llama-server 는 서버 하나에 모델 하나를 띄웁니다. 양자화 비교(7b)나 라우팅의 빠른 경로(6)에 다른 모델을 쓰려면 모델마다 포트를 달리해 띄우고, 이름 → 주소를 적습니다. 목록에 없는 모델은 `OPENAI_BASE_URL` 로 갑니다.

```dotenv
OPENAI_MODEL_URLS={"gemma-4-e4b-q8": "http://127.0.0.1:8082/v1", "gemma-4-e4b-q2": "http://127.0.0.1:8083/v1"}
```

메모리가 모자라면(모델 파일 크기 + KV 캐시만큼 RAM · 공유 GPU 메모리를 씀) `-c 8192 -np 1` 처럼 문맥 길이와 동시 처리 수를 줄이세요.

### 그림 근거 답변 (비전)

이미지 · 영상 장면 청크는 글이 파일 이름 · 시각 정도라, 글만 넘기면 LLM 은 그림을 보지 못한 채 답합니다. 답변 생성의 **그림 근거 첨부**(`images: true`, 연결 실행 경로의 `images`)를 켜면 근거 중 그림 청크를 JPEG(긴 변 768px)로 첨부하고 그 번호로 인용하게 합니다(최대 `max_images`, 기본 3장 — 그림 한 장이 근거 글 수백 자만큼 읽기 시간을 씀).

```powershell
# Gemma 4 E4B 는 비전 투영 파일(mmproj)을 함께 주면 그림을 읽는다 (google/gemma-4-E4B-it-qat-q4_0-gguf, 약 1GB)
llama-server.exe -m C:\Users\<사용자>\llm-models\gemma-4-E4B_q4_0-it.gguf --mmproj C:\Users\<사용자>\llm-models\gemma-4-E4B-it-mmproj.gguf `
  --host 127.0.0.1 --port 8081 -c 16384 -ngl 99 -np 2 --alias gemma-4-e4b
```

- OpenAI 호환은 `image_url`(data URI), Claude 는 `image`(base64) 블록으로 보냅니다. `--mmproj` 없이 띄운 서버는 그림을 거부하거나 무시합니다.
- 한계: 문장별 근거 검증(글자 · 의미)은 그림 내용을 모르므로, 그림을 인용한 문장은 '근거 약함'으로 나올 수 있습니다 — LLM 판정을 함께 보세요.

## 동작

- 429·5xx·과부하(529)·시간 초과는 지수 백오프로 최대 3번 다시 시도하고, 인증 오류 같은 4xx 는 바로 실패합니다.
- JSON 이 필요한 호출은 OpenAI 호환 API 에 `response_format: json_object` 를 보내고, 응답에 코드 블록이나 설명이 섞여 있어도 첫 JSON 객체/배열을 꺼냅니다.
- OpenAI 공식 API 에는 `max_completion_tokens`, 호환 서버에는 `max_tokens` 를 보냅니다.
- 입력·출력 토큰 수와 소요 시간을 함께 돌려줘 비용을 가늠할 수 있습니다.

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/llm/status` | 제공자별 설정 상태와 기본 제공자 (키 값 제외) |
| GET | `/api/llm/models` | OpenAI 호환 서버에 올라온 모델 이름 (`/v1/models`) |
| POST | `/api/llm/test` | 연결 시험 `{"provider"?, "model"?, "prompt"?}` → `{"text", "usage", "seconds", "tokens_per_second", "config"}` |

화면: **기록 · 설정 → LLM 연결**(`/settings/llm`) 에서 설정 상태 · 서버의 모델 목록 · 연결 시험을 볼 수 있습니다.
