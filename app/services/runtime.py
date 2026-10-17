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


def resolve_device() -> str:
    wanted = get_settings().device.lower()
    if wanted != "auto":
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
        "hf_token_set": bool(get_settings().hf_token or os.environ.get("HF_TOKEN")),
    }
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        info["cuda"] = {
            "name": props.name,
            "total_gb": round(props.total_memory / 2**30, 2),
            "allocated_gb": round(torch.cuda.memory_allocated(0) / 2**30, 2),
        }
    try:
        import psutil  # uvicorn[standard] 가 설치하지 않으면 생략

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
