"""IO2 실행 도구 샌드박스: LLM · 외부 에이전트가 만든 코드를 격리된 곳에서 돌린다.

Docker 가 있으면 컨테이너로 — 네트워크 없음 · 읽기 전용 파일 시스템(/tmp 만 쓰기) · 메모리 256MB · CPU 1 · 프로세스 64개 · 시간 상한.
없으면 별도 파이썬 프로세스로 돌리되(격리 모드 -I, 빈 작업 폴더, 비밀이 든 환경 변수 없음, 시간 상한) 네트워크 · 파일 접근은 막지 못해
결과에 isolation='process' 로 약하다고 표시한다 — 약한 격리를 강한 것처럼 보이면 안 된다.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

from app.core.config import get_settings

MAX_OUT = 20000


def docker_ok() -> bool:
    exe = shutil.which("docker")
    if not exe:
        return False
    try:
        return subprocess.run([exe, "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=10).returncode == 0
    except OSError, subprocess.TimeoutExpired:
        return False


def run_python(code: str, timeout: float | None = None) -> dict[str, Any]:
    """→ {stdout, stderr, exit_code, timed_out, isolation, seconds}."""
    st = get_settings()
    timeout = timeout or st.sandbox_timeout
    t0 = time.perf_counter()
    if docker_ok():
        cmd = ["docker", "run", "--rm", "-i", "--network", "none", "--memory", "256m", "--cpus", "1", "--pids-limit", "64", "--read-only",
               "--tmpfs", "/tmp:size=16m", "--security-opt", "no-new-privileges", "--cap-drop", "ALL", "--user", "65534:65534",
               st.sandbox_image, "python", "-I", "-"]  # fmt: skip
        isolation, env, cwd = "docker", None, None
    else:
        cwd = tempfile.mkdtemp(prefix="atlas_sbx_")
        # 비밀(토큰 · API 키)이 든 환경 변수를 넘기지 않는다 — 실행 파일을 찾는 데 필요한 것만
        env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "PYTHONIOENCODING")}
        env["PYTHONIOENCODING"] = "utf-8"
        # -I 는 -E 를 포함해 PYTHONIOENCODING 을 무시한다 — Windows 에서는 출력이 로캘(cp949)로 나와 UTF-8 로 읽으면 한글이 깨졌다.
        # -X utf8(UTF-8 모드)은 명령줄 옵션이라 -I 와 함께 써도 적용된다
        cmd, isolation = [sys.executable, "-I", "-X", "utf8", "-"], "process"
    try:
        p = subprocess.run(
            cmd, input=code.encode("utf-8"), capture_output=True, timeout=timeout + (20 if isolation == "docker" else 0), env=env, cwd=cwd
        )
        out = {"stdout": p.stdout.decode("utf-8", "replace")[:MAX_OUT], "stderr": p.stderr.decode("utf-8", "replace")[-4000:],
               "exit_code": p.returncode, "timed_out": False}  # fmt: skip
    except subprocess.TimeoutExpired:
        out = {"stdout": "", "stderr": f"시간 상한 {timeout:.0f}초를 넘어 멈췄습니다", "exit_code": None, "timed_out": True}
    finally:
        if cwd:
            shutil.rmtree(cwd, ignore_errors=True)
    # 컨테이너는 첫 실행에 이미지를 받느라 오래 걸릴 수 있어 프로세스 시간 상한에 여유를 두고, 코드 실행 자체는 python 안에서 막지 않는다 —
    # 대신 컨테이너의 CPU · 메모리 · 프로세스 상한이 무한 루프 · 폭탄을 막는다
    return out | {"isolation": isolation, "seconds": round(time.perf_counter() - t0, 2)}
