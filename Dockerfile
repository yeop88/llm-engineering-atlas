# LLM Engineering Atlas 앱 이미지.
#   docker compose --profile app up -d --build          # CPU (기본)
#   docker build --build-arg TORCH_EXTRA=cu130 -t atlas .   # NVIDIA GPU (docs/gpu.md)
# 데이터(SQLite · 업로드 · 공개 자료 캐시)는 /app/data, 모델 캐시는 /root/.cache/huggingface 볼륨에 둔다 —
# 이미지를 다시 만들어도 내려받은 모델과 실험 기록이 남게.
FROM python:3.14-slim-trixie

# uv 는 로컬 개발과 같은 버전으로 고정 (uv.lock 해석이 달라지지 않게)
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /bin/

ARG TORCH_EXTRA=cpu
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1

WORKDIR /app

# 의존성만 먼저 설치 — 코드만 바뀌면 이 층(수 GB 의 torch)은 캐시를 다시 쓴다
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --extra ${TORCH_EXTRA}

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY docs ./docs
COPY scripts ./scripts
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra ${TORCH_EXTRA}

VOLUME ["/app/data", "/root/.cache/huggingface"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# 0.0.0.0 으로 열리므로 사내망 · 서버에서는 API_TOKEN 을 꼭 설정한다 (docs/guides/deploy.md)
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
