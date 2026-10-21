"""S5 실측용 llama-server 띄우기: 설정(KV 캐시 비트 · 추측 디코딩)마다 서버를 따로 띄우고, 다 쓰면 끈다.

사람이 명령을 바꿔 가며 서버를 다시 띄우면 설정 · 순서 · 데우기가 매번 달라 비교가 흔들린다 — 그래서 앱이 같은 모델 · 같은 문맥 길이로
설정만 바꿔 차례로 띄운다. 메모리는 두 가지로 본다: 서버가 시작할 때 로그에 적는 KV 캐시 크기(정확 — 비트를 바꾼 효과가 바로 보임),
프로세스 RSS(CPU 메모리 — Vulkan · CUDA 로 GPU 에 올린 가중치는 여기 안 잡힌다).
"""

import re
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psutil

from app.core.config import get_settings

KV_LINE = re.compile(r"(?:KV self size|llama_kv_cache[^:]*:.*?size)\s*=\s*([\d.]+)\s*MiB", re.I)
SPEED_LINE = re.compile(r"draft acceptance rate\s*=\s*([\d.]+)", re.I)


def kv_mib(lines: list[str]) -> float | None:
    """로그의 KV 캐시 크기(MiB). llama.cpp 는 장치별 'KV buffer size' 줄과 합계 'size =' 줄을 함께 적어서, 둘을 모두 더하면
    두 배로 잡힌다(비트를 바꾼 효과 비교는 맞아도 절대 크기가 틀림). 합계 줄이 있으면 합계만(SWA 모델은 캐시가 둘이라 둘을 더함),
    없는 옛 형식이면 장치별 버퍼 줄을 더한다."""
    total, bufs = [], []
    for ln in lines:
        if m := KV_LINE.search(ln):
            (bufs if "buffer" in ln.lower() else total).append(float(m.group(1)))
    v = total or bufs
    return round(sum(v), 1) if v else None


@dataclass
class Variant:
    label: str
    kv_k: str = "f16"
    kv_v: str = "f16"
    draft: str | None = None  # 초안 모델 GGUF 파일 이름(추측 디코딩)
    draft_max: int = 16
    extra: list[str] = field(default_factory=list)


def free_port(start: int = 18100) -> int:
    for p in range(start, start + 200):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise RuntimeError("빈 포트가 없습니다")


class Server:
    def __init__(self, model: Path, v: Variant, ctx: int = 8192, ngl: int = 99):
        st = get_settings()
        if not st.llama_server_bin or not Path(st.llama_server_bin).exists():
            raise RuntimeError("LLAMA_SERVER_BIN(llama-server 실행 파일)이 설정되지 않았습니다 — .env")
        self.port, self.v, self.lines = free_port(), v, []
        cmd = [str(st.llama_server_bin), "-m", str(model), "--host", "127.0.0.1", "--port", str(self.port), "-c", str(ctx), "-ngl", str(ngl), "-np", "1",
               "--alias", v.label, "--no-webui"]  # fmt: skip
        if v.kv_k != "f16":
            cmd += ["--cache-type-k", v.kv_k]
        if v.kv_v != "f16":  # V 를 양자화하려면 flash attention 이 필요하다(llama.cpp)
            cmd += ["--cache-type-v", v.kv_v, "-fa", "on"]
        if v.draft:
            cmd += [
                "-md",
                str(Path(st.llm_models_dir or model.parent) / v.draft),
                "--draft-max",
                str(v.draft_max),
                "--draft-min",
                "1",
                "-ngld",
                str(ngl),
            ]
        self.cmd = cmd + v.extra
        self.proc = subprocess.Popen(
            self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace"
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:  # type: ignore[union-attr]
            self.lines.append(line.rstrip())
            if len(self.lines) > 4000:
                del self.lines[:1000]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def wait(self, timeout: float = 240) -> None:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError("서버가 시작하지 못했습니다: " + " / ".join(self.lines[-6:]))
            try:
                if httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=3).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
        raise RuntimeError("서버 시작 시간 초과")

    def memory(self) -> dict[str, Any]:
        kv = kv_mib(self.lines)
        acc = [float(m.group(1)) for ln in self.lines if (m := SPEED_LINE.search(ln))]
        try:
            rss = psutil.Process(self.proc.pid).memory_info().rss / 2**20
        except psutil.Error:
            rss = None
        return {"kv_cache_mib": kv, "rss_mib": round(rss, 1) if rss else None,
                "draft_acceptance": acc[-1] if acc else None}  # fmt: skip

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
