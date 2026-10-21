"""상호운용 IO2 실행 샌드박스: Docker 격리 옵션 · Docker 가 없을 때의 프로세스 대체(약한 격리 표시) · 시간 상한 · 비밀 차단.

Docker 는 실제로 띄우지 않는다 — 명령줄만 가로채 격리 옵션을 확인하고, 대체 경로는 별도 파이썬 프로세스로 실제로 돌린다.
"""

import subprocess
import sys

import pytest

from app.stages.interop import sandbox


@pytest.fixture
def no_docker(monkeypatch):
    monkeypatch.setattr(sandbox, "docker_ok", lambda: False)


def test_docker_ok_false_without_executable(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    assert sandbox.docker_ok() is False


def test_docker_ok_false_when_daemon_unreachable(monkeypatch):
    """docker 실행 파일은 있는데 데몬이 꺼져 있으면(흔한 경우) 컨테이너로 가지 않는다 — 가면 모든 실행이 실패한다."""
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: "docker")

    def boom(*a, **kw):
        raise subprocess.TimeoutExpired("docker", 10)

    monkeypatch.setattr(sandbox.subprocess, "run", boom)
    assert sandbox.docker_ok() is False


def test_docker_command_has_isolation_flags(monkeypatch):
    """컨테이너 경로: 네트워크 없음 · 읽기 전용 · 메모리 · CPU · 프로세스 상한 · 권한 없는 사용자 — 하나라도 빠지면 격리가 약해진다."""
    monkeypatch.setattr(sandbox, "docker_ok", lambda: True)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, stdout=b"42\n", stderr=b"")

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    r = sandbox.run_python("print(42)", timeout=5)
    cmd = seen["cmd"]
    pairs = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1) if cmd[i].startswith("--")}
    assert cmd[:2] == ["docker", "run"] and "--read-only" in cmd and "--rm" in cmd
    assert pairs["--network"] == "none" and pairs["--memory"] == "256m" and pairs["--pids-limit"] == "64"
    assert pairs["--user"] == "65534:65534" and pairs["--cap-drop"] == "ALL" and pairs["--security-opt"] == "no-new-privileges"
    assert cmd[-3:] == ["python", "-I", "-"] and seen["kw"]["input"] == b"print(42)"
    assert seen["kw"]["timeout"] == 25  # 첫 실행의 이미지 받기 여유(+20초)
    assert r["isolation"] == "docker" and r["stdout"] == "42\n" and r["exit_code"] == 0


def test_process_fallback_runs_and_marks_weak_isolation(no_docker):
    """Docker 가 없으면 별도 프로세스로 돌리되 isolation='process' — 약한 격리를 강한 것처럼 보이면 안 된다."""
    r = sandbox.run_python("print(sum(range(10)))\nprint('한글')", timeout=20)
    assert r["isolation"] == "process" and r["exit_code"] == 0 and r["timed_out"] is False
    assert r["stdout"].split() == ["45", "한글"]  # 한글 출력이 깨지지 않게 UTF-8 로


def test_process_fallback_hides_secret_env(no_docker, monkeypatch):
    """비밀(토큰 · API 키)이 든 환경 변수는 넘기지 않는다 — LLM 이 만든 코드가 os.environ 을 읽어 내보낼 수 있다."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    r = sandbox.run_python("import os; print(os.environ.get('OPENAI_API_KEY'))", timeout=20)
    assert r["stdout"].strip() == "None"


def test_process_fallback_uses_empty_temp_dir_and_cleans_up(no_docker, tmp_path):
    r = sandbox.run_python("import os; print(os.getcwd()); print(len(os.listdir('.')))", timeout=20)
    cwd, n = r["stdout"].split()
    assert "atlas_sbx_" in cwd and n == "0"
    import os

    assert not os.path.exists(cwd)  # 실행이 남긴 파일이 쌓이지 않게 지운다


def test_process_fallback_timeout(no_docker):
    """무한 루프는 시간 상한에서 멈춘다 — 멈추지 않으면 요청 스레드가 영원히 묶인다."""
    r = sandbox.run_python("while True: pass", timeout=1)
    assert r["timed_out"] is True and r["exit_code"] is None and "시간 상한" in r["stderr"]


def test_process_fallback_reports_errors_and_truncates(no_docker):
    r = sandbox.run_python(f"print('x' * {sandbox.MAX_OUT + 500})\nraise SystemExit(3)", timeout=20)
    assert r["exit_code"] == 3 and len(r["stdout"]) == sandbox.MAX_OUT
    err = sandbox.run_python("1/0", timeout=20)
    assert err["exit_code"] != 0 and "ZeroDivisionError" in err["stderr"]


def test_sandbox_api_is_admin_only(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(sandbox, "run_python", lambda code, timeout=None: {"stdout": "ok", "isolation": "process"})
    st = get_settings()
    monkeypatch.setattr(st, "api_token", "admin-tok")
    monkeypatch.setattr(st, "api_users", [{"token": "user-tok", "name": "kim", "role": "user"}])
    assert client.post("/api/interop/sandbox", json={"code": "print(1)"}, headers={"Authorization": "Bearer user-tok"}).status_code == 403
    r = client.post("/api/interop/sandbox", json={"code": "print(1)"}, headers={"Authorization": "Bearer admin-tok"}).json()
    assert r["isError"] is False and '"stdout": "ok"' in r["content"][0]["text"]
    calls = client.get(f"/api/interop/trace/{r['trace_key']}", headers={"Authorization": "Bearer admin-tok"}).json()["calls"]
    assert calls[0]["channel"] == "sandbox" and calls[0]["untrusted"] is True


def test_runs_with_current_interpreter(no_docker, monkeypatch):
    """대체 경로는 지금 파이썬(sys.executable)을 격리 모드(-I) · UTF-8 모드로 — PATH 의 다른 파이썬 · 작업 폴더의 모듈을 쓰지 않고, 한글 출력이 로캘 인코딩으로 깨지지 않게."""
    seen = {}
    monkeypatch.setattr(
        sandbox.subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd, kw=kw) or subprocess.CompletedProcess(cmd, 0, b"", b"")
    )
    sandbox.run_python("pass", timeout=3)
    assert seen["cmd"] == [sys.executable, "-I", "-X", "utf8", "-"] and seen["kw"]["timeout"] == 3
    assert set(seen["kw"]["env"]) <= {"PATH", "SYSTEMROOT", "TEMP", "TMP", "PYTHONIOENCODING", "Path", "SystemRoot", "Temp", "Tmp"}
