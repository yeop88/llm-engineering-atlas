"""단계 레지스트리(app/stages/registry.py)로 문서 색인(docs/README.md)과 단계별 README 를 만든다.

화면(메뉴 · 단계 설명 · 맵)과 문서가 같은 원본에서 나오도록 하기 위함이다. 레지스트리를 고친 뒤 실행:

    uv run python scripts/gen_docs.py          # 파일 생성/갱신
    uv run python scripts/gen_docs.py --check  # 최신인지 확인만 (테스트에서 사용)
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.stages import registry  # noqa: E402

GENERATED = "<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry.py)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->"

GUIDES = [
    ("guides/architecture.md", "아키텍처 — 코드 구조(core · stages · web)와 동작 방식"),
    ("guides/api.md", "REST API"),
    ("guides/data-processing.md", "데이터 처리 — 수집 · 전처리 · 평가 자료 기록과 유효하게 처리하는 법"),
    ("guides/deploy.md", "배포 · 운영 — Docker, 접근 토큰, 작업 기록, 모델 호환성 점검, 새 모델 후보"),
    ("guides/llm.md", "LLM 연결 — 로컬 llama.cpp · OpenAI 호환 · Claude, 소형 모델 비교"),
    ("guides/gpu.md", "CPU · CUDA · ROCm 설치"),
    ("guides/troubleshooting.md", "문제 해결"),
]
RECORDS = [
    ("records/model-verification.md", "대체 모델 정보 검증과 실측 벤치마크"),
    ("stages/5-finetune/finetune.md#실행-기록", "파인튜닝 실행 기록 (#1~#3)"),
    ("stages/2-rag/rag.md#검색-정확도-정책-정확-검색--근사-검색", "벡터 검색 재현율 문제와 정정 기록"),
]
STATUS_MARK = {registry.DONE: "✅", registry.BASIC: "🟡", registry.PLANNED: "⬜"}


def rel(from_file: str, to_path: str) -> str:
    path, _, anchor = to_path.partition("#")
    r = os.path.relpath(ROOT / path, (ROOT / from_file).parent).replace("\\", "/")
    return r + (f"#{anchor}" if anchor else "")


def stage_readme(s: registry.Stage) -> str:
    me = s.readme
    flow = registry.MAIN_FLOW
    lines = [
        GENERATED,
        "",
        f"# {s.no} · {s.title} ({s.en})",
        "",
        f"**상태: {STATUS_MARK[s.status]} {s.status_label}** — {s.summary}",
        "",
        "## 원리",
        "",
        s.principle,
        "",
        "## 왜 하는가",
        "",
        s.why,
        "",
        "## 어떻게 (이 앱에서)",
        "",
        *[f"- {h}" for h in s.how],
        "",
        "## 화면",
        "",
        *(
            [f"- `{p.href}` — **{p.label}**: {p.desc}" for p in s.pages]
            or ["- 아직 테스트 화면이 없습니다. 단계 소개는 앱의 `/stages/" + s.key + "` 에서 볼 수 있습니다."]
        ),
    ]
    if s.plans:
        lines += ["", "## 앞으로 할 일", "", *[f"- {p}" for p in s.plans]]
    if s.docs:
        lines += ["", "## 상세 문서", "", *[f"- [{t}]({rel(me, p)})" for t, p in s.docs]]
    if s.flow in ("main", "kg"):
        # 이전 · 다음은 같은 맵 안에서 (지식 그래프 맵은 K1 → K8)
        flow = registry.KG_FLOW if s.flow == "kg" else flow
        i = [x.key for x in flow].index(s.key)
        nav = []
        if i > 0:
            nav.append(f"← [{flow[i - 1].no} {flow[i - 1].title}]({rel(me, flow[i - 1].readme)})")
        nav.append(f"[전체 맵]({rel(me, s.map_info.doc)})")
        if i < len(flow) - 1:
            nav.append(f"[{flow[i + 1].no} {flow[i + 1].title}]({rel(me, flow[i + 1].readme)}) →")
        lines += ["", "---", "", " · ".join(nav)]
    return "\n".join(lines) + "\n"


def index() -> str:
    me = "docs/README.md"

    def rows(key: str) -> list[str]:
        maps = {m.doc for m in registry.MAPS}  # 맵 개요 문서는 표 위에 따로 걸므로 행마다 반복하지 않는다
        return [
            f"| {s.no} | [{s.title}]({rel(me, s.readme)}) | {STATUS_MARK[s.status]} {s.status_label} | {s.summary} | "
            + (" · ".join(f"[{t}]({rel(me, p)})" for t, p in s.docs if p not in maps) or "—")
            + " |"
            for s in registry.map_stages(key)
        ]

    return "\n".join(
        [
            GENERATED,
            "",
            "# 문서",
            "",
            "LLM Engineering Atlas 의 문서는 맵의 단계 순서로 정리되어 있습니다. 맵은 둘입니다 — [LLM 시스템 엔지니어링 맵](map.md) · [지식 그래프 · GraphRAG 맵](kg-map.md). 각 단계 폴더의 `README.md` 에 그 단계의 **원리 · 왜 하는가 · 어떻게(이 앱에서)** 가 있고, 같은 폴더에 상세 문서가 있습니다.",
            "",
            "```",
            "[데이터 임베딩] → [RAG 검색] → [리랭킹 (정밀 필터링)]",
            "                                        ↓",
            "[라우팅 (난이도 분류)] → 쉬운 질문:  [지식 증류 · 양자화된 소형 모델]",
            "                       → 어려운 질문: [파인튜닝 · 강화학습된 에이전트 LLM]",
            "```",
            "",
            "## LLM 시스템 엔지니어링 맵",
            "",
            "| # | 단계 | 상태 | 무엇을 | 상세 문서 |",
            "|---|---|---|---|---|",
            *rows("llm"),
            "",
            "## 지식 그래프 · GraphRAG 맵",
            "",
            "```",
            "[요구사항 정의] → [온톨로지 설계] → [데이터 추출 (ETL · LLM)] → [지식 융합 · 정제]",
            "                                        ↓",
            "                              [그래프 DB (Neo4j)]",
            "                                        ↓",
            "  GraphRAG: [Text2Cypher] · [그래프 하이브리드 검색] · [글로벌 커뮤니티 요약]",
            "```",
            "",
            "| # | 단계 | 상태 | 무엇을 | 상세 문서 |",
            "|---|---|---|---|---|",
            *rows("kg"),
            "",
            "## 가이드",
            "",
            *[f"- [{d}]({p})" for p, d in GUIDES],
            "",
            "## 기록",
            "",
            *[f"- [{d}]({p})" for p, d in RECORDS],
            "",
        ]
    )


def outputs() -> dict[str, str]:
    out = {"docs/README.md": index()}
    for s in registry.STAGES:
        out[s.readme] = stage_readme(s)
    return out


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for path, text in outputs().items():
        f = ROOT / path
        cur = f.read_text(encoding="utf-8") if f.exists() else None
        if cur != text:
            stale.append(path)
            if not check:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text, encoding="utf-8", newline="\n")
    if check and stale:
        print("최신이 아닌 문서:", ", ".join(stale), "— uv run python scripts/gen_docs.py 로 다시 만드세요.")
        return 1
    print("갱신" if stale and not check else "최신", len(stale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
