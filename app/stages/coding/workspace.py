"""작업 공간 · 도구 · 깬 코드 과제(CD3 · CD4 · CD6).

작업 공간 = 저장소의 app · tests · migrations · 설정 파일을 복사한 폴더(data/coding/work/<이름>/). 에이전트는 복사본만 고치고, 테스트도
복사본에서 같은 파이썬으로 돌린다(PYTHONPATH = 작업 공간) — 저장소 원본과 실행 중인 서버를 건드리지 않게.

도구: 코드 찾기(index) · 파일 읽기(줄 범위) · 정확한 문자열 교체(파일에 정확히 한 번 있어야 함 — 전체를 다시 쓰면 고치지 않은 곳이 바뀐다) ·
테스트 실행(시간 상한) · 린트(ruff) · 원본과의 차이(diff).

깬 코드 과제: 테스트가 부르는 모듈의 함수에 작은 돌연변이(비교 뒤집기 · 경계 하나 밀기 · and/or · 상수 ±1)를 넣고, 그 테스트 파일이
실제로 실패하는 것만 과제로 둔다(살아남은 돌연변이는 테스트가 못 잡는 것이라 과제가 아님). 공개 벤치마크와 달리 학습 데이터에 섞였을 수
없고, 정답(원래 줄)이 정해져 있다.
"""

import ast
import difflib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from app.core.config import BASE_DIR, get_settings

COPY = ["app", "tests", "migrations", "scripts", "alembic.ini", "pyproject.toml"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "presets_cache")
DEFAULT_TESTS = ["tests/core/test_stats.py", "tests/stages/voice/test_stt_speech.py", "tests/stages/voice/test_logic.py",
                 "tests/stages/edge/test_devices_offline_privacy.py", "tests/stages/edge/test_pack_sync.py"]  # fmt: skip


def root() -> Path:
    d = get_settings().data_dir / "coding"
    (d / "work").mkdir(parents=True, exist_ok=True)
    (d / "tasks").mkdir(parents=True, exist_ok=True)
    return d


def _name(s: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", s):
        raise ValueError("이름은 영문 · 숫자 · _ · - 만")
    return s


def base_copy() -> Path:
    """깨끗한 복사본 하나(과제마다 여기서 다시 복사) — 저장소 전체를 매번 읽지 않으려고."""
    d = root() / "base"
    if not d.exists():
        d.mkdir(parents=True)
        for x in COPY:
            src = BASE_DIR / x
            if src.is_dir():
                shutil.copytree(src, d / x, ignore=IGNORE)
            elif src.exists():
                shutil.copy2(src, d / x)
    return d


def refresh_base() -> None:
    shutil.rmtree(root() / "base", ignore_errors=True)
    base_copy()


def workspace(name: str, fresh: bool = True) -> Path:
    ws = root() / "work" / _name(name)
    if fresh:
        shutil.rmtree(ws, ignore_errors=True)
        shutil.copytree(base_copy(), ws)
    return ws


def _safe(ws: Path, rel: str) -> Path:
    p = (ws / rel).resolve()
    if ws.resolve() not in p.parents:
        raise ValueError(f"작업 공간 밖 경로: {rel}")
    return p


def read(ws: Path, rel: str, start: int = 1, end: int | None = None) -> str:
    lines = _safe(ws, rel).read_text(encoding="utf-8").splitlines()
    end = min(len(lines), end or start + 80)
    return "\n".join(f"{i:>4} {lines[i - 1]}" for i in range(max(1, start), end + 1))


def replace(ws: Path, rel: str, old: str, new: str) -> dict[str, Any]:
    p = _safe(ws, rel)
    s = p.read_text(encoding="utf-8")
    n = s.count(old)
    if n != 1:
        return {"ok": False, "error": f"바꿀 글이 파일에 {n}번 있습니다 — 정확히 한 번 있는 글(앞뒤 줄 포함)로 주세요"}
    p.write_text(s.replace(old, new), encoding="utf-8", newline="\n")
    try:
        ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        p.write_text(s, encoding="utf-8", newline="\n")  # 문법이 깨진 패치는 되돌린다 — 다음 단계가 깨진 파일 위에 쌓이지 않게
        return {"ok": False, "error": f"문법 오류라 되돌렸습니다: {exc}"}
    return {"ok": True}


def run_tests(ws: Path, paths: list[str], timeout: float = 180) -> dict[str, Any]:
    env = os.environ | {"PYTHONPATH": str(ws), "PYTHONIOENCODING": "utf-8"}
    env.pop("DATA_DIR", None)  # 테스트의 conftest 가 임시 폴더를 정한다
    t = time.perf_counter()
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", *paths, "-q", "-x", "-p", "no:cacheprovider", "--no-header"], cwd=ws, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)  # fmt: skip
        out, code = (r.stdout + r.stderr)[-4000:], r.returncode
    except subprocess.TimeoutExpired:
        out, code = f"시간 상한 {timeout}초를 넘었습니다", -1
    return {"passed": code == 0, "code": code, "output": out, "seconds": round(time.perf_counter() - t, 1)}


def lint(ws: Path, paths: list[str]) -> dict[str, Any]:
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *paths, "--no-cache"],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return {"ok": r.returncode == 0, "output": (r.stdout + r.stderr)[-2000:]}


def diff(ws: Path) -> str:
    """원본(base)과 작업 공간의 차이 — app · tests 의 .py 만."""
    base = base_copy()
    out = []
    for f in sorted(list((ws / "app").rglob("*.py")) + list((ws / "tests").rglob("*.py"))):
        rel = f.relative_to(ws).as_posix()
        b = base / rel
        a_txt = b.read_text(encoding="utf-8").splitlines() if b.exists() else []
        w_txt = f.read_text(encoding="utf-8").splitlines()
        if a_txt != w_txt:
            out += difflib.unified_diff(a_txt, w_txt, f"a/{rel}", f"b/{rel}", lineterm="", n=2)
    return "\n".join(out)


# ── 깬 코드 과제 ─────────────────────────────────────────────────────────────
FLIP = {ast.Lt: "<=", ast.LtE: "<", ast.Gt: ">=", ast.GtE: ">", ast.Eq: "!=", ast.NotEq: "=="}
SYM = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!="}


def mutations(src: str) -> list[dict[str, Any]]:
    """한 줄 안에서 끝나는 돌연변이 후보: 비교 연산자 바꾸기 · and/or · 작은 정수 ±1."""
    tree = ast.parse(src)
    lines = src.splitlines()
    out = []
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in funcs:
        for n in ast.walk(fn):
            if not hasattr(n, "lineno") or n.lineno != n.end_lineno:  # 여러 줄 · 위치 없는 마디(arguments 등)는 한 줄 돌연변이 대상이 아님
                continue
            line = lines[n.lineno - 1]
            if isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in FLIP:
                seg = line[n.col_offset : n.end_col_offset]
                op = SYM[type(n.ops[0])]
                if seg.count(op) == 1:
                    out.append(
                        {
                            "func": fn.name,
                            "line": n.lineno,
                            "kind": "비교 뒤집기",
                            "old": seg,
                            "new": seg.replace(op, FLIP[type(n.ops[0])], 1),
                        }
                    )
            elif isinstance(n, ast.BoolOp) and len(n.values) == 2:
                seg = line[n.col_offset : n.end_col_offset]
                a, b = (" and ", " or ") if isinstance(n.op, ast.And) else (" or ", " and ")
                if seg.count(a) == 1:
                    out.append({"func": fn.name, "line": n.lineno, "kind": "and/or", "old": seg, "new": seg.replace(a, b)})
            elif isinstance(n, ast.Constant) and type(n.value) is int and 0 < n.value <= 100:
                seg = line[n.col_offset : n.end_col_offset]
                if seg == str(n.value):
                    out.append(
                        {"func": fn.name, "line": n.lineno, "kind": "상수 ±1", "old": seg, "new": str(n.value + 1), "col": n.col_offset}
                    )
    return out


def _modules_of_test(ws: Path, test: str) -> list[str]:
    src = (ws / test).read_text(encoding="utf-8")
    mods = set()
    for m in re.finditer(r"^from (app(?:\.\w+)+) import (.+)$", src, re.M):
        base, names = m.group(1), [x.strip().split(" as ")[0] for x in m.group(2).strip("()").split(",")]
        for nm in names:
            for cand in (f"{base}.{nm}", base):
                p = ws / (cand.replace(".", "/") + ".py")
                if p.exists():
                    mods.add(p.relative_to(ws).as_posix())
                    break
    # 설정 · DB 모델은 값 모음이라 돌연변이가 테스트로 잡히지 않는다 — 시험만 늘리므로 뺀다
    return sorted(m for m in mods if m not in ("app/core/config.py", "app/core/db.py"))


def apply_mutation(ws: Path, file: str, m: dict[str, Any]) -> None:
    p = ws / file
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    ln = lines[m["line"] - 1]
    if "col" in m:
        i = m["col"]
        lines[m["line"] - 1] = ln[:i] + m["new"] + ln[i + len(m["old"]) :]
    else:
        lines[m["line"] - 1] = ln.replace(m["old"], m["new"], 1)
    p.write_text("".join(lines), encoding="utf-8", newline="\n")


def build_tasks(name: str, tests: list[str], n: int, seed: int = 7, progress=lambda f, m: None) -> dict[str, Any]:
    """테스트 파일마다 그 테스트가 가져오는 모듈의 돌연변이를 섞어, 테스트가 실패하는 것만 n 개까지."""
    rnd = random.Random(seed)
    base = base_copy()
    cands = []
    for t in tests:
        for f in _modules_of_test(base, t):
            for m in mutations((base / f).read_text(encoding="utf-8")):
                cands.append((t, f, m))
    rnd.shuffle(cands)
    tasks, tried, survived = [], 0, 0
    ws = workspace(f"{name}-probe")
    for t, f, m in cands:
        if len(tasks) >= n or tried >= n * 6:
            break
        tried += 1
        progress(len(tasks) / n, f"돌연변이 시험 {tried} · 과제 {len(tasks)}/{n}")
        shutil.copy2(base / f, ws / f)
        apply_mutation(ws, f, m)
        r = run_tests(ws, [t], timeout=120)
        shutil.copy2(base / f, ws / f)
        if r["passed"]:
            survived += 1
            continue
        tasks.append({"id": f"c{len(tasks) + 1}", "test": t, "file": f, **m, "failing": r["output"][-1500:],
                      "issue": f"테스트 {t} 가 실패합니다. 원인을 찾아 app/ 의 코드를 고치세요(테스트는 고치지 마세요).\n\n실패 출력:\n{r['output'][-1500:]}"})  # fmt: skip
    shutil.rmtree(ws, ignore_errors=True)
    data = {"name": name, "tests": tests, "tasks": tasks, "tried": tried, "survived": survived}
    (root() / "tasks" / f"{_name(name)}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: v for k, v in data.items() if k != "tasks"} | {"n": len(tasks)}


def load_tasks(name: str) -> dict[str, Any]:
    p = root() / "tasks" / f"{_name(name)}.json"
    if not p.exists():
        raise ValueError(f"과제가 없습니다: {name}")
    return json.loads(p.read_text(encoding="utf-8"))


def list_tasks() -> list[dict[str, Any]]:
    out = []
    for p in sorted((root() / "tasks").glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append(
            {"name": d["name"], "n": len(d["tasks"]), "tried": d.get("tried"), "survived": d.get("survived"), "tests": d.get("tests")}
        )
    return out
