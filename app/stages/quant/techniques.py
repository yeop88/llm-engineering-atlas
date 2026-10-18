"""양자화 기술 카탈로그 (2026-10 기준). 화면에서 원리 · 특징을 보여 주고, 실행 가능한 것은 골라서 조합 실험에 넣는다.

나눈 기준: 무엇을 줄이나
- vector: 색인에 저장하는 임베딩 벡터 (검색 메모리 · 디스크)
- dim: 벡터 차원 수 (Matryoshka) — 엄밀히는 양자화가 아니지만 같은 목적(크기 줄이기)이라 정밀도와 함께 조합한다
- weight: 임베딩 모델 가중치 (인코딩 속도 · 모델 메모리)
- llm: LLM 가중치 · KV 캐시 (답변 생성 속도 · 메모리) — 서버(llama-server)를 그 설정으로 띄워 비교한다

run=True 는 이 앱이 직접 실행하는 것, False 는 원리 설명과 사용법만 둔 것(별도 의존성 · GPU · 벡터 DB 설정이 필요).
"""

from typing import Any

TECHNIQUES: list[dict[str, Any]] = [
    # ── 벡터 ──────────────────────────────────────────────────────────────
    {
        "key": "float32",
        "group": "vector",
        "name": "float32 (기준)",
        "bits": 32,
        "run": True,
        "principle": "부호 1 · 지수 8 · 가수 23비트 실수. 모델이 내놓는 그대로의 임베딩.",
        "pros": "손실 없음",
        "cons": "가장 큼 (1024차원 = 4KB)",
        "when": "다른 정밀도의 손실을 재는 기준",
    },
    {
        "key": "float16",
        "group": "vector",
        "name": "float16 (반정밀도)",
        "bits": 16,
        "run": True,
        "principle": "지수 5 · 가수 10비트. 정규화된 임베딩(값이 −1~1)은 범위 문제가 없어 반올림 오차만 생긴다.",
        "pros": "메모리 1/2, 사실상 무손실",
        "cons": "압축률이 낮음",
        "when": "정확도를 전혀 잃고 싶지 않을 때의 첫 단계 (pgvector halfvec 등)",
    },
    {
        "key": "int8",
        "group": "vector",
        "name": "int8 스칼라 양자화 (SQ8)",
        "bits": 8,
        "run": True,
        "principle": "차원마다 문서 임베딩의 최소~최대를 256칸으로 나눠 정수로 저장(보정 = calibration). 검색은 정수 내적.",
        "pros": "메모리 1/4, 손실이 보통 1%p 안팎",
        "cons": "보정 자료(문서 분포)가 필요, 분포가 바뀌면 다시 보정",
        "when": "가장 무난한 기본값 (Qdrant scalar quantization 등)",
    },
    {
        "key": "int4",
        "group": "vector",
        "name": "int4 스칼라 양자화 (SQ4)",
        "bits": 4,
        "run": True,
        "principle": "int8 과 같은 방식으로 16칸만 쓴다. 한 바이트에 두 차원.",
        "pros": "메모리 1/8",
        "cons": "int8 보다 손실이 큼",
        "when": "binary 는 손실이 너무 크고 int8 은 큰 경우의 중간",
    },
    {
        "key": "binary",
        "group": "vector",
        "name": "binary (1비트)",
        "bits": 1,
        "run": True,
        "principle": "값이 0보다 크면 1, 아니면 0. 거리는 서로 다른 비트 수(해밍 거리) — XOR 와 popcount 로 매우 빠르다.",
        "pros": "메모리 1/32, 검색이 가장 빠름",
        "cons": "단독으로는 손실이 큼(차원이 작은 모델일수록)",
        "when": "재점수와 함께 1차 후보 검색용",
    },
    {
        "key": "binary_rescore",
        "group": "vector",
        "name": "binary + int8 재점수",
        "bits": 1,
        "run": True,
        "principle": "binary 해밍 거리로 후보를 k × 배수만큼 넉넉히 뽑고, 디스크의 int8 벡터와 float32 질의로 후보만 다시 점수.",
        "pros": "RAM 은 binary 만큼, 정확도는 int8 에 가까움",
        "cons": "디스크 읽기 · 2단계 지연",
        "when": "대규모 색인의 표준 구성 (2단계 검색)",
    },
    {
        "key": "pq",
        "group": "vector",
        "name": "곱 양자화 (PQ)",
        "bits": 8,
        "run": True,
        "principle": "벡터를 m 조각으로 나누고 조각마다 k-means 코드북(256개)을 학습해 조각을 코드 번호 1바이트로 저장. 검색은 질의 조각과 코드북의 거리표로 계산(ADC).",
        "pros": "m 바이트로 매우 작음 (1024차원 → m=64 면 64B)",
        "cons": "코드북 학습 필요, 조각 수가 적으면 손실 큼",
        "when": "수억 개 규모 (FAISS · Milvus IVF-PQ, Qdrant product quantization)",
    },
    {
        "key": "rabitq",
        "group": "vector",
        "name": "RaBitQ (설명)",
        "bits": 1,
        "run": False,
        "principle": "벡터를 무작위로 회전한 뒤 1비트로 줄이고, 내적 추정값에 오차 보정항과 오차 한계를 함께 계산한다. 단순 binary 보다 같은 비트에서 정확하고 오차 범위를 알 수 있다.",
        "pros": "1~수 비트에서 binary 보다 정확, 이론적 오차 한계",
        "cons": "구현이 복잡 — 벡터 DB · 라이브러리 내장 기능으로 쓴다",
        "when": "벡터 DB 가 지원하면 binary 대신 고려",
    },
    # ── 차원 ──────────────────────────────────────────────────────────────
    {
        "key": "mrl",
        "group": "dim",
        "name": "Matryoshka 차원 축소 (MRL)",
        "bits": None,
        "run": True,
        "principle": "앞쪽 차원에 중요한 정보가 몰리도록 학습된 모델(EmbeddingGemma · Qwen3-Embedding 등)은 앞 d 차원만 잘라 다시 정규화해도 품질이 크게 줄지 않는다.",
        "pros": "정밀도 양자화와 곱으로 줄어듦 (256차원 + binary = 32B)",
        "cons": "MRL 로 학습하지 않은 모델은 손실이 큼",
        "when": "정밀도와 함께 조합 — 이 앱의 인덱스 truncate_dim 과 같은 원리",
    },
    # ── 임베딩 모델 가중치 ────────────────────────────────────────────────
    {
        "key": "w_fp32",
        "group": "weight",
        "name": "모델 float32 (기준)",
        "bits": 32,
        "run": True,
        "principle": "모델 가중치를 32비트 실수로 계산.",
        "pros": "기준",
        "cons": "CPU 에서 느리고 메모리 큼",
        "when": "기준",
    },
    {
        "key": "w_bf16",
        "group": "weight",
        "name": "모델 bfloat16",
        "bits": 16,
        "run": True,
        "principle": "지수 8 · 가수 7비트. float32 와 같은 범위라 넘침(NaN)이 없다. float16 은 EmbeddingGemma 에서 NaN 이 나서 쓰지 않는다.",
        "pros": "메모리 1/2",
        "cons": "bf16 연산을 지원하지 않는 CPU 에서는 오히려 느릴 수 있음",
        "when": "GPU · 최신 CPU",
    },
    {
        "key": "w_int8",
        "group": "weight",
        "name": "모델 int8 동적 양자화",
        "bits": 8,
        "run": True,
        "principle": "Linear 층 가중치를 int8 로 저장하고, 활성값은 실행 중에 int8 로 바꿔 정수 행렬곱을 한다(PyTorch dynamic quantization, CPU).",
        "pros": "CPU 인코딩이 빨라지고 메모리 감소, 보정 자료 불필요",
        "cons": "CPU 전용, 모델에 따라 정확도 손실",
        "when": "GPU 없는 서버에서 임베딩 인코딩 속도",
    },
    {
        "key": "w_onnx",
        "group": "weight",
        "name": "ONNX · OpenVINO int8 (설명)",
        "bits": 8,
        "run": False,
        "principle": "모델을 ONNX · OpenVINO 그래프로 바꾸고 보정 자료로 정적 int8 양자화. sentence-transformers 의 backend='onnx' · 'openvino' 로 불러 쓴다.",
        "pros": "CPU 에서 가장 빠른 축",
        "cons": "optimum 등 추가 의존성 · 변환 과정",
        "when": "운영 배포 단계",
    },
    # ── LLM ───────────────────────────────────────────────────────────────
    {
        "key": "gguf_legacy",
        "group": "llm",
        "name": "GGUF Q8_0 · Q4_0 (블록 양자화)",
        "bits": "8 · 4",
        "run": True,
        "principle": "가중치를 32개씩 블록으로 묶어 블록마다 배율(scale) 하나와 정수로 저장. Q8_0 은 거의 무손실, Q4_0 은 단순하고 빠르다.",
        "pros": "모든 하드웨어에서 빠름",
        "cons": "같은 4비트라도 K · I 양자화보다 손실이 큼",
        "when": "기준(Q8_0) · 속도 우선",
    },
    {
        "key": "gguf_k",
        "group": "llm",
        "name": "GGUF K 양자화 (Q6_K · Q5_K_M · Q4_K_M · Q3_K · Q2_K)",
        "bits": "2~6",
        "run": True,
        "principle": "256개 슈퍼블록 안에 작은 블록마다 배율을 두고, 중요한 텐서(어텐션 출력 등)는 더 높은 비트로 섞어 쓴다(_M · _S 는 섞는 정도).",
        "pros": "같은 크기에서 legacy 보다 정확, Q4_K_M 이 흔한 기본값",
        "cons": "2 · 3비트는 품질 저하가 뚜렷",
        "when": "일반적인 로컬 배포",
    },
    {
        "key": "gguf_i",
        "group": "llm",
        "name": "GGUF I 양자화 (IQ4_XS · IQ3 · IQ2) + imatrix",
        "bits": "2~4",
        "run": True,
        "principle": "가중치 묶음을 미리 정한 격자 · 코드북의 가장 가까운 점으로 표현. 보정 문장으로 구한 중요도 행렬(imatrix)로 중요한 가중치의 오차를 줄인다.",
        "pros": "3비트 이하에서 K 양자화보다 정확",
        "cons": "CPU 에서 K 양자화보다 느릴 수 있음",
        "when": "메모리가 아주 작을 때",
    },
    {
        "key": "gguf_dynamic",
        "group": "llm",
        "name": "동적 혼합 비트 (Unsloth Dynamic UD-*)",
        "bits": "2~8",
        "run": True,
        "principle": "층 · 텐서마다 민감도를 재서 민감한 곳은 높은 비트, 둔감한 곳은 낮은 비트로 섞는다.",
        "pros": "같은 평균 비트에서 손실이 작음",
        "cons": "파일마다 구성이 달라 비교가 어렵다",
        "when": "2 · 3비트로 줄여야 할 때",
    },
    {
        "key": "qat",
        "group": "llm",
        "name": "양자화 인식 학습 (QAT)",
        "bits": 4,
        "run": True,
        "principle": "학습 단계에서 양자화 오차를 흉내 내 모델이 그 오차에 강해지게 한 뒤 양자화한다(예: Gemma 4 QAT q4_0). 학습 후 양자화(PTQ)보다 같은 비트에서 손실이 작다.",
        "pros": "4비트에서도 원본에 가까움",
        "cons": "모델 제공자가 QAT 판을 내야 쓸 수 있음",
        "when": "제공되면 4비트의 첫 선택",
    },
    {
        "key": "kv_cache",
        "group": "llm",
        "name": "KV 캐시 양자화",
        "bits": "8 · 4",
        "run": True,
        "principle": "생성 중 쌓이는 어텐션 키 · 값을 q8_0 · q4_0 으로 저장(llama-server --cache-type-k / --cache-type-v, V 는 flash attention 필요). 가중치 양자화와 따로 적용된다.",
        "pros": "긴 문맥 · 동시 요청의 메모리 감소",
        "cons": "q4 는 긴 문맥에서 품질 저하 가능",
        "when": "근거를 많이 넣는 RAG · 동시 처리",
    },
    {
        "key": "gpu_formats",
        "group": "llm",
        "name": "GPU 서버용 (GPTQ · AWQ · FP8 · MXFP4 · NVFP4) (설명)",
        "bits": "4~8",
        "run": False,
        "principle": "GPTQ 는 층별로 오차를 보정하며 반올림, AWQ 는 활성값이 큰 채널의 가중치를 보호, FP8 · MXFP4 · NVFP4 는 블록 배율을 둔 저비트 부동소수점으로 최신 GPU 가 하드웨어로 계산한다.",
        "pros": "vLLM · TensorRT-LLM 등 GPU 서빙에서 빠름",
        "cons": "GPU 필요 (이 PC 는 내장 GPU)",
        "when": "GPU 서버 배포",
    },
]

BY_KEY = {t["key"]: t for t in TECHNIQUES}
GROUPS = {"vector": "임베딩 벡터 정밀도", "dim": "차원", "weight": "임베딩 모델 가중치", "llm": "LLM 가중치 · KV 캐시"}

# llama-server 실행 명령을 조합할 때 쓰는 값 (가중치 파일은 사용자가 고른 GGUF)
KV_TYPES = ["f16", "q8_0", "q4_0"]


def llama_command(model_path: str, alias: str, port: int, kv_k: str = "f16", kv_v: str = "f16", ctx: int = 8192) -> str:
    """가중치 양자화(GGUF 파일) × KV 캐시 양자화를 동시에 적용한 서버 실행 명령. V 캐시를 양자화하려면 flash attention 이 필요하다."""
    parts = [f'llama-server.exe -m "{model_path}" --host 127.0.0.1 --port {port} -c {ctx} -ngl 99 -np 1 --alias {alias}']
    if kv_k != "f16":
        parts.append(f"--cache-type-k {kv_k}")
    if kv_v != "f16":
        parts.append(f"--cache-type-v {kv_v} -fa on")
    return " ".join(parts)
