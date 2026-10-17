# CPU · GPU(CUDA / ROCm) 설치

PyTorch 는 가속기별로 다른 빌드를 씁니다. `pyproject.toml` 의 extra 로 하나를 골라 설치합니다.

| 환경 | 명령 | PyTorch 빌드 | 지원 OS |
|---|---|---|---|
| CPU 전용 | `uv sync --extra cpu` | `2.14.1+cpu` | Windows · Linux · macOS |
| NVIDIA GPU (CUDA 12.6) | `uv sync --extra cu126` | `2.14.1+cu126` | Windows · Linux |
| NVIDIA GPU (CUDA 13.0) | `uv sync --extra cu130` | `2.14.1+cu130` | Windows · Linux |
| AMD GPU (ROCm 7.2) | `uv sync --extra rocm` | `2.14.1+rocm7.2` | **Linux 전용** |

- extra 없이 `uv sync` 하면 PyPI 기본 torch 가 설치됩니다(Windows=CPU, Linux=CUDA).
- 하나만 고를 수 있습니다(동시에 지정하면 uv 가 거부).
- **CUDA 버전 고르기**: 최신 드라이버(R580 이상)면 cu130, 오래된 드라이버면 cu126. `nvidia-smi` 오른쪽 위 "CUDA Version" 이상인 것을 고르세요.
- **ROCm**: PyTorch 공식 ROCm 빌드는 Linux 용만 배포됩니다. Windows + AMD GPU 는 현재 CPU 빌드를 쓰세요. ROCm 빌드는 내부적으로 `triton-rocm` 을 함께 설치합니다.

## 설정

`.env` 의 `DEVICE` 로 장치를 고릅니다.

| 값 | 동작 |
|---|---|
| `auto` (기본) | GPU(CUDA·ROCm)가 있으면 GPU, Apple Silicon 이면 MPS, 아니면 CPU |
| `cpu` | 항상 CPU |
| `cuda`, `cuda:1` | NVIDIA GPU (또는 ROCm 빌드의 AMD GPU) |
| `rocm` | AMD GPU. PyTorch ROCm 빌드는 내부적으로 `cuda` 장치 이름을 쓰므로 `cuda` 와 같게 처리 |

GPU 를 지정했는데 쓸 수 없으면(예: CPU 빌드 설치) 시작할 때 원인과 설치 명령을 알려 줍니다. 대시보드의 시스템 정보에서 설치된 빌드(`cpu` / `cuda` / `rocm`), CUDA·ROCm 버전, GPU 이름과 메모리를 확인할 수 있습니다.

`DTYPE=auto` 는 bfloat16 을 지원하는 GPU 에서 bfloat16, 그 밖에는 float32 를 씁니다. float16 은 EmbeddingGemma 계열에서 NaN 이 생겨 자동으로는 쓰지 않습니다.

## 확인

```bash
uv run python -c "from app.core.runtime import accelerator; print(accelerator())"
```
