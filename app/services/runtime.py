"""디바이스/정밀도 결정 및 시스템 정보."""

import os
import platform
import sys
import threading
from collections import deque
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

import torch

from app.config import get_settings


def accelerator() -> dict:
    """설치된 PyTorch 빌드와 사용 가능한 가속기.
    ROCm(AMD) 빌드도 PyTorch 안에서는 장치 이름이 'cuda' 이므로 torch.version.hip 으로 구분한다."""
    hip = getattr(torch.version, "hip", None)
    build = "rocm" if hip else ("cuda" if torch.version.cuda else "cpu")
    info = {
        "build": build,
        "torch": torch.__version__,
        "cuda_version": torch.version.cuda,
        "rocm_version": hip,
        "available": False,
        "devices": [],
    }
    if torch.cuda.is_available():
        info["available"] = True
        info["devices"] = [
            {
                "index": i,
                "name": torch.cuda.get_device_name(i),
                "total_gb": round(torch.cuda.get_device_properties(i).total_memory / 2**30, 1),
            }
            for i in range(torch.cuda.device_count())
        ]
    return info


def resolve_device() -> str:
    wanted = get_settings().device.lower()
    if wanted in ("rocm", "hip"):  # PyTorch ROCm 빌드는 'cuda' 장치 이름을 쓴다
        wanted = "cuda"
    if wanted != "auto":
        if wanted.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                f"DEVICE={get_settings().device} 이지만 GPU 를 쓸 수 없습니다. 설치된 PyTorch: {accelerator()['build']} 빌드. 'uv sync --extra cu126|cu130|rocm' 로 GPU 빌드를 설치하세요."
            )
        return wanted
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def resolve_dtype(device: str | None = None) -> torch.dtype:
    """float16 은 EmbeddingGemma 계열에서 NaN 을 유발하므로 auto 모드에서는 쓰지 않는다."""
    wanted = get_settings().dtype.lower()
    if wanted in ("float32", "fp32"):
        return torch.float32
    if wanted in ("bfloat16", "bf16"):
        return torch.bfloat16
    if wanted in ("float16", "fp16"):
        return torch.float16
    device = device or resolve_device()
    if device == "cuda" and torch.cuda.is_bf16_supported():
        return torch.bfloat16
    return torch.float32


class MemorySampler:
    """대시보드 메모리 차트용: 일정 간격으로 프로세스/시스템 메모리를 기록하는 링 버퍼."""

    def __init__(self, interval: float = 5.0, keep: int = 120):
        self.interval = interval
        self._buf: deque[dict] = deque(maxlen=keep)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        import psutil

        from app.services.model_manager import get_manager  # 순환 import 방지

        vm = psutil.virtual_memory()
        self._buf.append(
            {
                "t": datetime.now(UTC).isoformat(),
                "process_gb": round(psutil.Process().memory_info().rss / 2**30, 3),
                "used_gb": round((vm.total - vm.available) / 2**30, 2),
                "total_gb": round(vm.total / 2**30, 1),
                "loaded": len(get_manager().loaded()),
            }
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._sample()
            except Exception:  # 표본 하나 실패해도 계속
                pass
            self._stop.wait(self.interval)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="memory-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def samples(self) -> list[dict]:
        return list(self._buf)


sampler = MemorySampler()


def _pkg(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "-"


def system_info() -> dict:
    device = resolve_device()
    info: dict = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "device": device,
        "dtype": str(resolve_dtype(device)).replace("torch.", ""),
        "torch_threads": torch.get_num_threads(),
        "packages": {
            p: _pkg(p)
            for p in ("fastapi", "uvicorn", "sentence-transformers", "transformers", "torch", "huggingface-hub", "sqlalchemy", "pydantic")
        },
        "cuda": None,
        "accelerator": accelerator(),
        "hf_token_set": bool(get_settings().hf_token or os.environ.get("HF_TOKEN")),
    }
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        info["cuda"] = {
            "name": props.name,
            "backend": "ROCm " + torch.version.hip if getattr(torch.version, "hip", None) else f"CUDA {torch.version.cuda}",
            "total_gb": round(props.total_memory / 2**30, 2),
            "allocated_gb": round(torch.cuda.memory_allocated(0) / 2**30, 2),
        }
    try:
        import psutil

        vm = psutil.virtual_memory()
        rss = psutil.Process().memory_info().rss
        info["memory"] = {
            "total_gb": round(vm.total / 2**30, 1),
            "available_gb": round(vm.available / 2**30, 1),
            "process_gb": round(rss / 2**30, 2),
        }
    except ImportError:
        info["memory"] = None
    return info
