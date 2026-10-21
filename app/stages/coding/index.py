"""CD1 코드 검색 · 저장소 이해: 함수 · 클래스 단위로 나누고 기호(이름) · 호출 관계로 찾는다.

문서 검색과 다른 점: 코드는 함수 하나가 뜻의 단위이고, 질문(이슈 · 실패한 테스트 출력)에는 함수 이름 · 파일 경로 · 오류 줄이 그대로
나온다. 그래서 BM25 낱말을 식별자 기준으로 나누고(snake_case · CamelCase · 점), 이름이 질문에 그대로 나오면 크게 더하며(기호 일치),
실패한 테스트가 부른 함수 · 그 함수가 부르는 함수를 이웃으로 더한다(호출 그래프). 세 방법을 같은 과제로 비교한다(정답 = 깨뜨린 함수).
"""

import ast
import re
from pathlib import Path
from typing import Any

from app.stages.rag.bm25 import BM25Index

WORD = re.compile(r"[A-Za-z][a-z0-9]*|[A-Z]+(?![a-z])|\d+|[가-힣]{2,}")


def tokens(text: str) -> list[str]:
    out = []
    for part in re.split(r"[^A-Za-z0-9_가-힣]+", text or ""):
        if not part:
            continue
        low = part.lower()
        out.append(low)
        subs = [w.lower() for w in WORD.findall(part.replace("_", " "))]
        if len(subs) > 1:
            out += subs
    return out


def chunks(root: Path, sub: str = "app") -> list[dict[str, Any]]:
    """파일마다 최상위 함수 · 클래스 · 메서드 하나씩. 호출하는 이름(calls)과 줄 범위를 함께."""
    out = []
    for f in sorted((root / sub).rglob("*.py")):
        rel = f.relative_to(root).as_posix()
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.splitlines()
        mod = rel.removesuffix(".py").replace("/", ".")
        for node in tree.body:
            nodes = [(node, None)]
            if isinstance(node, ast.ClassDef):
                nodes += [(n, node.name) for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for n, cls in nodes:
                if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if isinstance(n, ast.ClassDef) and cls is None and nodes[1:]:
                    body = "\n".join(lines[n.lineno - 1 : n.body[0].lineno])  # 클래스는 머리만(메서드는 따로)
                else:
                    body = "\n".join(lines[n.lineno - 1 : n.end_lineno])
                calls = sorted({c.func.id if isinstance(c.func, ast.Name) else c.func.attr for c in ast.walk(n) if isinstance(c, ast.Call)
                                and isinstance(c.func, (ast.Name, ast.Attribute))})  # fmt: skip
                name = f"{cls}.{n.name}" if cls else n.name
                out.append({"id": len(out), "file": rel, "module": mod, "name": name, "short": n.name, "start": n.lineno, "end": n.end_lineno, "text": body,
                            "doc": ast.get_docstring(n) or "", "calls": calls})  # fmt: skip
    return out


class CodeIndex:
    def __init__(self, root: Path):
        self.root = root
        self.items = chunks(root)
        self.bm = BM25Index([c["id"] for c in self.items], [tokens(f"{c['file']} {c['name']} {c['text']}") for c in self.items])
        self.by_short: dict[str, list[int]] = {}
        for c in self.items:
            self.by_short.setdefault(c["short"], []).append(c["id"])

    def search(self, query: str, k: int = 10, method: str = "graph", seed_names: list[str] | None = None) -> list[dict[str, Any]]:
        """method: bm25 · symbol(이름 일치 가산) · graph(+ 호출 이웃). seed_names = 실패한 테스트가 부른 이름들."""
        scores: dict[int, float] = {i: s for i, s in self.bm.search(tokens(query), top_k=200)}
        if method in ("symbol", "graph"):
            mentioned = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query))
            for name in mentioned | set(seed_names or []):
                for i in self.by_short.get(name, []):
                    scores[i] = scores.get(i, 0) + 8.0
            files = set(re.findall(r"app/[\w/]+\.py", query))
            for c in self.items:
                if c["file"] in files:
                    scores[c["id"]] = scores.get(c["id"], 0) + 3.0
        if method == "graph":
            top = sorted(scores, key=lambda i: -scores[i])[:5]
            for i in top:
                for callee in self.items[i]["calls"]:
                    for j in self.by_short.get(callee, []):
                        scores[j] = scores.get(j, 0) + 0.3 * scores[i] / max(1, len(self.items[i]["calls"]))
        ranked = sorted(scores, key=lambda i: -scores[i])[:k]
        return [{k2: self.items[i][k2] for k2 in ("file", "name", "start", "end", "doc")} | {"score": round(scores[i], 2)} for i in ranked]


def test_calls(test_src: str) -> list[str]:
    """테스트가 부르는 이름(모듈.함수 꼴의 함수 이름) — 호출 이웃의 출발점."""
    try:
        tree = ast.parse(test_src)
    except SyntaxError:
        return []
    return sorted({c.func.attr for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)})
