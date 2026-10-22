"""단계 레지스트리(app/stages/registry/)로 문서 색인(docs/README.md) · 단계별 README · 맵 개요 · 저장소 README 의 맵 표를 만든다.

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

GENERATED = "<!-- 이 파일은 scripts/gen_docs.py 가 단계 레지스트리(app/stages/registry/)로 만듭니다. 내용을 바꾸려면 레지스트리를 고친 뒤 다시 실행하세요. -->"

GUIDES = [
    ("guides/architecture.md", "아키텍처 — 코드 구조(core · stages · web)와 동작 방식"),
    ("guides/api.md", "REST API"),
    ("guides/ui.md", "화면(UI) — 화면 뼈대 · 새 화면 만들기 · 부품 · 작업 맥락 · 스타일 · 접근성"),
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
STATUS_MARK = {registry.DONE: "✅", registry.BASIC: "🟡", registry.PLANNED: "⬜", registry.RESEARCH: "🔬", registry.HOLD: "⏸"}


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
    "  guides/                                 여러 단계에 걸친 가이드 (아키텍처 · API · 화면 · 데이터 처리 · 배포 · LLM · 설치 · 문제 해결)",
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
    return " · ".join(f"{STATUS_MARK[c]} {st.count(c)}" for c in registry.STATUSES if st.count(c))


def index() -> str:
    me = "docs/README.md"
    return "\n".join(
        [
            GENERATED,
            "",
            "# 문서",
            "",
            f"LLM Engineering Atlas 의 문서는 **맵 → 단계** 순서로 정리되어 있습니다. 맵 {len(registry.MAPS)}개 · 단계 {len(registry.STAGES)}개. "
            "모든 맵이 같은 규칙을 따릅니다 — 맵 이름 하나를 화면 주소(`/maps/<맵>`) · 개요(`maps/<맵>.md`) · 단계 폴더(`stages/<맵>/`)에 같이 씁니다.",
            "",
            "## 구조",
            "",
            *TREE,
            "",
            "- 단계 폴더 이름 = `<번호>-<이름>` (번호는 소문자, 이름은 레지스트리 키에서 맵 접두어를 뺀 것 — 예: `as1-intake`, `k1-requirements`, `m-multimodal`)",
            "- 생성 문서(색인 · 단계 README · 공통 맵 개요 · 맵 개요의 단계 표)는 레지스트리(`app/stages/registry/`)를 고친 뒤 `uv run python scripts/gen_docs.py` 로 다시 만듭니다.",
            "- 상태: ✅ 구현됨 · 🟡 기초 있음(기능은 다른 맵에 있고, 이 맵의 관점으로 묶은 화면 · 측정은 아직) · ⬜ 예정 · 🔬 연구(이 PC · 공개 모델로는 아직 제대로 돌릴 수 없어 설계 · 흉내 실험만) · ⏸ 보류",
            f"- 맵은 LLM 생태계 그룹 A~F 로 나뉩니다. 생태계 맵 {len(registry.ecosystem.ECOSYSTEM)}개(M1~M30 · E1~E4)와 이 앱의 맵의 대응 · 공통 온톨로지 · 통합 라우팅은 [LLM 생태계 구조](maps/ecosystem.md)에 있습니다.",
            "",
            "## 맵",
            "",
            "| 그룹 | 맵 | 무엇을 | 단계 | 개요 | 화면 |",
            "|---|---|---|---|---|---|",
            *[
                f"| {m.group} | **{m.title}** | {m.summary} | {len(registry.map_stages(m.key))} — {counts(m.key)} | [{m.slug}.md]({rel(me, m.doc)}) | `{m.href}` |"
                for g, _, _ in registry.ecosystem.GROUPS
                for m in registry.MAPS
                if m.group == g
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


README_START = "<!-- 맵 표: scripts/gen_docs.py 가 레지스트리로 채웁니다. 이 표시 사이는 고치지 마세요. -->"
README_END = "<!-- /맵 표 -->"


def readme_map_table() -> str:
    """README 의 맵 표: 맵이 늘고 단계를 구현할 때마다 README 를 손으로 고치다 어긋났다(맵 18개인데 한 줄로만 소개) — 레지스트리로 채운다."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        raise SystemExit(f"README.md 에 맵 표 표시({README_START} … {README_END})가 없습니다.")
    me = "README.md"
    st = [s.status for s in registry.STAGES]
    rows = [
        "| 그룹 | 맵 | 무엇을 | 단계 | ✅ | 🟡 | ⬜ | 🔬 | 화면 · 개요 |",
        "|---|---|---|---|---|---|---|---|---|",
        *[
            f"| {m.group} | **{m.title.removesuffix(' 맵')}** | {m.summary.rsplit(' — ', 1)[-1]} | {len(ss)} | {n(ss, registry.DONE)} | {n(ss, registry.BASIC)} | {n(ss, registry.PLANNED)} "
            f"| {n(ss, registry.RESEARCH)} | `{m.href}` · [개요]({rel(me, m.doc)}) |"
            for g, _, _ in registry.ecosystem.GROUPS
            for m in registry.MAPS
            if m.group == g
            for ss in [[s.status for s in registry.map_stages(m.key)]]
        ],
        f"| | **합계 {len(registry.MAPS)}개** | | {len(st)} | {st.count(registry.DONE)} | {st.count(registry.BASIC)} | {st.count(registry.PLANNED)} "
        f"| {st.count(registry.RESEARCH)} | `/maps` · [생태계 구조](docs/maps/ecosystem.md) |",
    ]
    head, rest = text.split(README_START, 1)
    _, tail = rest.split(README_END, 1)
    return head + README_START + "\n" + "\n".join(rows) + "\n" + README_END + tail


ECO_DOC = "docs/maps/ecosystem.md"


def ecosystem_doc() -> str:
    """LLM 생태계 구조 문서: 생태계 맵(M1~M30 · E1~E4) ↔ 이 앱의 맵 대응 · 온톨로지 · 통합 라우팅 · 맵 메타데이터. 화면 /maps/ecosystem 과 같은 데이터."""
    eco, me = registry.ecosystem, ECO_DOC

    def link(k: str) -> str:
        m = registry.MAP_BY_KEY.get(k)
        return f"[{m.title.removesuffix(' 맵')}]({rel(me, m.doc)})" if m else k

    lines = [
        GENERATED,
        "",
        "# LLM 생태계 구조",
        "",
        f"LLM 생태계를 기술 영역 {len(eco.ECOSYSTEM)}개(M1~M30 · 확장 E1~E4)로 나누고, 이 앱의 맵 {len(registry.MAPS)}개가 어디를 덮는지 잇습니다. "
        "생태계 맵은 기술 영역의 목록이고 이 앱의 맵은 실행 구조라, 같게 만들지 않고 대응표로 잇습니다. 구현 상태(단계 상태)와 기술 성숙도(기초 · 성숙 · 신선 · 실험적)는 다른 축입니다. "
        "화면은 `/maps/ecosystem`, 데이터는 `app/stages/registry/ecosystem.py` 입니다.",
        "",
        "## 설계 원칙",
        "",
        *[f"- {p}" for p in eco.PRINCIPLES],
        "",
    ]
    for g, title, areas in eco.GROUPS:
        lines += [
            f"## {g}. {title}",
            "",
            f"영역: {' · '.join(areas)}",
            "",
            "| 번호 | 생태계 맵 | 성숙도 | 우선순위 | 흐름 | 이 앱에서 | 단계 상태 |",
            "|---|---|---|---|---|---|---|",
        ]
        for e in eco.ECOSYSTEM:
            if e.group != g:
                continue
            keys = ([e.new] if e.new else []) + list(e.covers)
            ss = [s.status for k in keys for s in registry.map_stages(k)]
            where = " · ".join(link(k) + (" (새 맵)" if k == e.new else "") for k in keys) or "—"
            lines.append(
                f"| {e.id} | {e.title} | {e.maturity} | {e.priority} | {e.flow} | {where} | "
                + (" · ".join(f"{STATUS_MARK[c]} {ss.count(c)}" for c in registry.STATUSES if ss.count(c)) or "—")
                + " |"
            )
        notes = [e for e in eco.ECOSYSTEM if e.group == g and e.note]
        if notes:
            lines += ["", *[f"- **{e.id}** {e.note}" for e in notes]]
        lines.append("")
    lines += ["## 공통 노드 온톨로지", "", "| 노드 | 뜻 | 예 |", "|---|---|---|", *[f"| `{a}` | {b} | {c} |" for a, b, c in eco.NODE_TYPES], "",
              "관계:", "", *[f"- `{a} -[{r}]-> {b}`" for a, r, b in eco.RELATIONS], "",
              "## 통합 라우팅", "", "| 단계 | 나누는 것 | 맡는 맵 |", "|---|---|---|",
              *[f"| {st} | {what} | {' · '.join(link(k) for k in keys)} |" for st, what, keys in eco.ROUTING], "",
              "## 맵 메타데이터", "", "| 맵 | 그룹 | 생태계 | 성숙도 | 기대는 맵 | 근거 수준 | 확인한 날 |", "|---|---|---|---|---|---|---|",
              *[f"| {link(m.key)} | {m.group} | {' '.join(m.eco) or '—'} | {m.maturity} | {' · '.join(link(k) for k in m.depends_on) or '—'} "
                f"| {eco.EVIDENCE.get(m.evidence_level, m.evidence_level)} | {m.last_verified_at} |" for m in registry.MAPS], ""]  # fmt: skip
    return "\n".join(lines)


def n(statuses: list[str], code: str) -> str:
    return str(statuses.count(code)) if statuses.count(code) else "—"


def outputs() -> dict[str, str]:
    out = {"docs/README.md": index(), "README.md": readme_map_table(), ECO_DOC: ecosystem_doc()}
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
    # Windows 콘솔(cp949)은 '—' 같은 글자를 못 써서 --check 실패 메시지를 내다 오류로 끝났다 — 못 쓰는 글자는 바꿔 출력
    sys.stdout.reconfigure(errors="replace")
    raise SystemExit(main())
