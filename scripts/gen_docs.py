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
    ("stages/llm/5-finetune/finetune.md#실행-기록", "파인튜닝 실행 기록 (#1~#3)"),
    ("stages/llm/2-rag/rag.md#검색-정확도-정책-정확-검색--근사-검색", "벡터 검색 재현율 문제와 정정 기록"),
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
    if s.builds_on:
        lines += ["", "## 기반 단계", "", "이미 있는 단계 위에 짓습니다.", "",
                  *[f"- [{registry.BY_KEY[k].no} {registry.BY_KEY[k].title}]({rel(me, registry.BY_KEY[k].readme)}) — "
                    f"{registry.BY_KEY[k].map_info.title} · {STATUS_MARK[registry.BY_KEY[k].status]} {registry.BY_KEY[k].status_label}" for k in s.builds_on]]  # fmt: skip
    flow = registry.map_flow(s)  # 이전 · 다음은 같은 맵 안에서
    if flow:
        i = [x.key for x in flow].index(s.key)
        nav = []
        if i > 0:
            nav.append(f"← [{flow[i - 1].no} {flow[i - 1].title}]({rel(me, flow[i - 1].readme)})")
        nav.append(f"[전체 맵]({rel(me, s.map_info.doc)})")
        if i < len(flow) - 1:
            nav.append(f"[{flow[i + 1].no} {flow[i + 1].title}]({rel(me, flow[i + 1].readme)}) →")
        lines += ["", "---", "", " · ".join(nav)]
    return "\n".join(lines) + "\n"


MARK_START = "<!-- 단계 표: scripts/gen_docs.py 가 레지스트리로 채웁니다. 이 표시 사이는 고치지 마세요. -->"
MARK_END = "<!-- /단계 표 -->"
TREE = [
    "```",
    "docs/",
    "  README.md                               이 색인 (생성)",
    "  maps/<맵>.md                            맵 개요 — 모든 맵에 같은 '단계' 표 (전용 화면이 있는 맵은 직접 쓴 개요 + 생성 표)",
    "  stages/<맵>/<번호>-<이름>/README.md       단계 문서: 원리 · 왜 · 어떻게 · 화면 · 할 일 · 기반 단계 (생성)",
    "  stages/<맵>/<번호>-<이름>/*.md            그 단계의 상세 문서 · 실측 기록 (직접 씀)",
    "  guides/                                 여러 단계에 걸친 가이드 (아키텍처 · API · 데이터 처리 · 배포 · LLM · 설치 · 문제 해결)",
    "  records/                                단계 밖의 실측 · 정정 기록",
    "```",
]


def stage_table(me: str, key: str) -> list[str]:
    """모든 맵 개요에 같은 모양으로 들어가는 단계 표 — 맵마다 표 모양이 달라 찾기 어려웠던 것을 맞춘다."""
    maps = {m.doc for m in registry.MAPS}  # 맵 개요 문서는 상세 문서 열에서 뺀다(이미 그 문서 안)
    rows = []
    for s in registry.map_stages(key):
        base = " · ".join(f"[{registry.BY_KEY[k].no} {registry.BY_KEY[k].menu}]({rel(me, registry.BY_KEY[k].readme)})" for k in s.builds_on)
        detail = " · ".join(f"[{t}]({rel(me, p)})" for t, p in s.docs if p.split("#")[0] not in maps)
        rows.append(
            f"| {s.no} | [{s.title}]({rel(me, s.readme)}) | {STATUS_MARK[s.status]} {s.status_label} | {s.summary} | {base or '—'} | {detail or '—'} |"
        )
    return ["| # | 단계 | 상태 | 무엇을 | 기반 단계 | 상세 문서 |", "|---|---|---|---|---|---|", *rows]


def counts(key: str) -> str:
    st = [s.status for s in registry.map_stages(key)]
    return " · ".join(f"{STATUS_MARK[c]} {st.count(c)}" for c in (registry.DONE, registry.BASIC, registry.PLANNED) if st.count(c))


def index() -> str:
    me = "docs/README.md"
    return "\n".join(
        [
            GENERATED,
            "",
            "# 문서",
            "",
            f"LLM Engineering Atlas 의 문서는 **맵 → 단계** 순서로 정리되어 있습니다. 맵 {len(registry.MAPS)}개 · 단계 {len(registry.STAGES)}개. "
            "모든 맵이 같은 규칙을 따릅니다 — 맵 이름 하나를 화면 주소(`/maps/<맵>`, LLM 맵은 `/roadmap`) · 개요(`maps/<맵>.md`) · 단계 폴더(`stages/<맵>/`)에 같이 씁니다.",
            "",
            "## 구조",
            "",
            *TREE,
            "",
            "- 단계 폴더 이름 = `<번호>-<이름>` (번호는 소문자, 이름은 레지스트리 키에서 맵 접두어를 뺀 것 — 예: `as1-intake`, `k1-requirements`, `m-multimodal`)",
            "- 생성 문서(색인 · 단계 README · 공통 맵 개요 · 맵 개요의 단계 표)는 레지스트리(`app/stages/registry.py`)를 고친 뒤 `uv run python scripts/gen_docs.py` 로 다시 만듭니다.",
            "- 상태: ✅ 구현됨 · 🟡 기초 있음(기능은 다른 맵에 있고, 이 맵의 관점으로 묶은 화면 · 측정은 아직) · ⬜ 예정",
            "",
            "## 맵",
            "",
            "| 맵 | 무엇을 | 단계 | 개요 | 화면 |",
            "|---|---|---|---|---|",
            *[
                f"| **{m.title}** | {m.summary} | {len(registry.map_stages(m.key))} — {counts(m.key)} | [{m.slug}.md]({rel(me, m.doc)}) | `{m.href}` |"
                for m in registry.MAPS
            ],
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


def map_doc(m: registry.Map) -> str:
    """공통 화면 맵의 개요 문서(docs/maps/<slug>.md)."""
    me = m.doc
    others = [o for o in registry.MAPS if o.key != m.key]
    lines = [
        GENERATED, "", f"# {m.title}", "", m.summary, "", m.lead, "",
        f"앱의 **맵 → {m.title}**(`{m.href}`)과 단계 소개(`/stages/<단계>`)에 같은 내용이 있습니다. "
        "**기초 있음** = 기능은 다른 맵에 있고(기반 단계), 이 맵의 관점으로 묶은 화면 · 측정은 아직인 단계입니다.", "",
        "## 전체 흐름", "", "```", *m.diagram.splitlines(), "```", "",
        "## 단계", "", *stage_table(me, m.key),
        "", "## 설계 원칙", "", *[f"- {p}" for p in m.principles],
        "", "## 예시", "", m.example,
        "", "---", "", "다른 맵: " + " · ".join(f"[{o.title}]({rel(me, o.doc)})" for o in others),
    ]  # fmt: skip
    return "\n".join(lines) + "\n"


def fill_stage_table(m: registry.Map) -> str:
    """직접 쓴 맵 개요(LLM · 지식 그래프 · 멀티에이전트)의 표시 사이에 단계 표만 채운다 — 나머지 글은 손으로 쓴 그대로."""
    text = (ROOT / m.doc).read_text(encoding="utf-8")
    if MARK_START not in text or MARK_END not in text:
        raise SystemExit(f"{m.doc} 에 단계 표 표시({MARK_START} … {MARK_END})가 없습니다.")
    head, rest = text.split(MARK_START, 1)
    _, tail = rest.split(MARK_END, 1)
    return head + MARK_START + "\n" + "\n".join(stage_table(m.doc, m.key)) + "\n" + MARK_END + tail


def outputs() -> dict[str, str]:
    out = {"docs/README.md": index()}
    for m in registry.MAPS:
        out[m.doc] = map_doc(m) if m.generated_doc else fill_stage_table(m)
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
