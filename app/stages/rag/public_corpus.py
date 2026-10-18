"""공개 자료 가져오기: Hugging Face 의 공개 데이터셋에서 한 분야의 문서 묶음을 골라 RAG 컬렉션 문서로 넣는다.

왜 만들었나
- 평가 세트가 작으면(문서 4건 · 24문항) 모든 비교가 '차이 불확실'로 끝난다. 실제 서비스 분야(법률 · 상담)에 가까운
  공개 문서로 컬렉션을 크게 만들어야 라우팅 · 에이전트 · 리랭킹처럼 '어려운 질문'에서 효과가 나는 기술을 잴 수 있다.
- 프리셋으로 둔 이유: 무엇을 어떤 기준으로 골랐는지가 코드에 남아 같은 컬렉션을 다시 만들 수 있게(재현성).
- 데이터셋 서버 API(조건 조회 · 검색)는 실측 당시 오류가 잦아, 원본 파일을 한 번 받아 data/public/ 에 두고 로컬에서 거른다.
  두 번째부터는 받지 않는다.
- 법령 · 판결은 저작권법 제7조의 비보호 저작물이고, 데이터셋 라이선스(공공누리 1유형 · openrail)와 출처를 문서마다 기록한다.

문서 모양: 법령은 법령 하나 = 문서 하나('제N조(제목) 내용' 줄 — 법령 청킹이 조문 단위로 자른다),
판례는 판례 하나 = 문서 하나(【판시사항】【판결요지】【참조조문】【전문】 — 판결문 청킹이 구획 단위로 자른다).
"""

import json
import re
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.jobs import Job

HF = "https://huggingface.co"

PRESETS: dict[str, dict[str, Any]] = {
    "labor_lease_law": {
        "title": "근로 · 주택임대차 법령과 판례",
        "description": "근로기준법 · 최저임금법 · 주택임대차보호법(시행령 포함) 조문 전체와, 그 법령을 참조조문으로 인용한 대법원 판례. "
        "법령과 판례가 서로 연결되어 '조문 + 판례'를 엮는 질문을 만들 수 있다. 일상 상담(임금 · 해고 · 보증금)과 가까운 분야.",
        "statutes": {
            "dataset": "smhilee/korean-law-dataset",
            "license": "공공누리 제1유형 (출처: 국가법령정보, 데이터셋 smhilee/korean-law-dataset)",
            "laws": ["근로기준법", "근로기준법 시행령", "최저임금법", "최저임금법 시행령", "주택임대차보호법", "주택임대차보호법 시행령"],
        },
        "precedents": {
            "dataset": "joonhok-exo-ai/korean_law_open_data_precedents",
            "license": "openrail (출처: 법원 판례 공개 데이터, 데이터셋 joonhok-exo-ai/korean_law_open_data_precedents)",
            "refs": ["근로기준법", "최저임금법", "주택임대차보호법"],
            "court": "대법원",
            "max": 240,
            "full_text_chars": 4000,  # 전문은 길어(수만 자) 앞부분만 — 판시사항 · 요지가 핵심이고 색인 · 질문 생성 비용을 맞추려고
        },
    }
}


def cache_dir(dataset: str) -> Path:
    d = get_settings().data_dir / "public" / dataset.replace("/", "__")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _files(c: httpx.Client, dataset: str, suffix: str) -> list[dict[str, Any]]:
    tree = c.get(f"{HF}/api/datasets/{dataset}/tree/main", params={"recursive": "true"}).json()
    return sorted((f for f in tree if f.get("type") == "file" and f["path"].endswith(suffix)), key=lambda f: f["path"])


def _download(c: httpx.Client, dataset: str, path: str, size: int) -> Path:
    """한 번만 받는다(크기가 같으면 건너뜀). 끊겨도 .part 를 지우고 다시 받으면 되게 단순하게 둔다."""
    out = cache_dir(dataset) / path.replace("/", "__")
    if out.exists() and out.stat().st_size == size:
        return out
    tmp = out.with_suffix(out.suffix + ".part")
    with c.stream("GET", f"{HF}/datasets/{dataset}/resolve/main/{path}") as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(out)
    return out


def _law_text(rows: list[dict[str, Any]]) -> str:
    """조문 행들 → '제N조(제목) 내용 / ① 항 / 1. 호' 줄. 법령 청킹이 '제N조' 를 경계로 자르게 조문마다 새 줄로 시작한다.

    원본은 '호' 하나가 한 행이라 같은 조문 머리 · 같은 항이 호마다 되풀이된다(제2조 머리가 9번). 그대로 이으면 청크가
    반복 글로 차고 검색 점수도 왜곡되므로, 직전에 쓴 조문 · 항과 같으면 다시 쓰지 않는다.
    """

    def items(v: Any) -> list[str]:
        return [x.strip() for x in (v if isinstance(v, list) else [v]) if isinstance(x, str) and x.strip()]

    lines: list[str] = []
    last_art = last_hang = None
    for r in rows:
        art = (r.get("조문내용") or "").strip()
        if art and art != last_art:
            lines.append(art)
            last_art, last_hang = art, None
        for h in items(r.get("항내용")):
            if h != last_hang and h not in art:
                lines.append(h)
                last_hang = h
        for h in items(r.get("호내용")):
            if h not in art and (not lines or lines[-1] != h):
                lines.append(h)
    return "\n".join(lines)


def collect_statutes(job: Job, spec: dict[str, Any], lo: float, hi: float) -> list[dict[str, Any]]:
    wanted = set(spec["laws"])
    by_law: dict[str, list[dict[str, Any]]] = {}
    meta: dict[str, dict[str, Any]] = {}
    with httpx.Client(timeout=120, follow_redirects=True) as c:
        files = _files(c, spec["dataset"], ".jsonl")
        for i, f in enumerate(files):
            job.update(lo + (hi - lo) * i / len(files), f"법령 파일 {i + 1}/{len(files)} 받기 · 거르기")
            path = _download(c, spec["dataset"], f["path"], f.get("size", -1))
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if not any(w in line for w in wanted):  # json 파싱 전에 문자열로 먼저 걸러 빠르게
                        continue
                    r = json.loads(line)
                    if r.get("법령명") in wanted:
                        by_law.setdefault(r["법령명"], []).append(r)
                        meta.setdefault(r["법령명"], {"시행일자": r.get("시행일자"), "소관부처": r.get("소관부처")})
    docs = []
    for law in spec["laws"]:
        rows = by_law.get(law) or []
        if not rows:
            continue
        # 조문번호 순(같은 조문의 항 · 호가 여러 행이면 원래 순서 유지)
        rows.sort(key=lambda r: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", str(r.get("조문번호") or ""))])
        m = meta[law]
        docs.append({"filename": f"{law}.txt", "text": f"{law}\n시행 {m['시행일자']} · 소관 {m['소관부처']}\n\n" + _law_text(rows),
                     "source": {"dataset": spec["dataset"], "license": spec["license"], "kind": "statute", "law": law, "articles": len(rows)}})  # fmt: skip
    return docs


def collect_precedents(job: Job, spec: dict[str, Any], lo: float, hi: float) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    cols = [
        "판례정보일련번호",
        "사건명",
        "사건번호",
        "선고일자",
        "법원명",
        "사건종류명",
        "판시사항",
        "판결요지",
        "참조조문",
        "참조판례",
        "전문",
    ]
    picked: list[dict[str, Any]] = []
    with httpx.Client(timeout=300, follow_redirects=True) as c:
        files = _files(c, spec["dataset"], ".parquet")
        for i, f in enumerate(files):
            job.update(lo + (hi - lo) * i / len(files), f"판례 파일 {i + 1}/{len(files)} 받기 · 거르기 ({f.get('size', 0) // 2**20}MB)")
            t = pq.read_table(_download(c, spec["dataset"], f["path"], f.get("size", -1)), columns=cols).to_pylist()
            for r in t:
                refs = r.get("참조조문") or ""
                if (
                    r.get("법원명") == spec.get("court", r.get("법원명"))
                    and any(x in refs for x in spec["refs"])
                    and (r.get("판결요지") or "").strip()
                ):
                    picked.append(r)
    # 최근 판례부터, 법령별로 고르게(한 법령 판례만 몰리지 않게) — 질문이 여러 분야에 걸치도록
    picked.sort(key=lambda r: str(r.get("선고일자") or ""), reverse=True)
    per = max(1, spec["max"] // len(spec["refs"]))
    out, count = [], dict.fromkeys(spec["refs"], 0)
    for r in picked:
        law = next(x for x in spec["refs"] if x in (r.get("참조조문") or ""))
        if count[law] < per:
            count[law] += 1
            out.append(r)
    docs = []
    for r in out[: spec["max"]]:
        full = (r.get("전문") or "").strip()
        text = "\n".join([
            f"{r['사건명']} ({r['법원명']} {r['선고일자']} 선고 {r['사건번호']})",
            f"【판시사항】 {r.get('판시사항') or ''}", f"【판결요지】 {r.get('판결요지') or ''}",
            f"【참조조문】 {r.get('참조조문') or ''}", f"【참조판례】 {r.get('참조판례') or ''}",
            f"【전문】 {full[: spec['full_text_chars']]}" + (" …(이하 생략)" if len(full) > spec["full_text_chars"] else ""),
        ])  # fmt: skip
        name = re.sub(r'[\\/:*?"<>|]', "_", f"판례 {r['사건번호']} {r['사건명']}")[:120]
        docs.append({"filename": f"{name}.txt", "text": text,
                     "source": {"dataset": spec["dataset"], "license": spec["license"], "kind": "precedent", "case_no": r["사건번호"],
                                "id": r.get("판례정보일련번호")}})  # fmt: skip
    return docs
