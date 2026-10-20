"""D1 수집 · 연결: 허용된 폴더(공유 폴더 · 내려받은 위키 내보내기 등)를 읽어 새 · 바뀐 · 지운 파일만 컬렉션에 반영한다.

서버의 아무 폴더나 읽지 못하게 INGEST_ROOTS(기본 data/inbox) 아래만 허용한다. 파일마다 출처 경로 · 수정 시각 · 해시를 문서 meta 에 남겨
다음 동기화 때 비교한다 — 같은 해시면 건너뛰고(중복 색인 방지), 바뀌었으면 옛 문서를 지우고 새로 넣는다(증분 갱신 D6 이 그 청크만
다시 만든다), 폴더에서 사라졌으면 문서도 지운다. interval_min 을 주면 앱이 주기적으로 동기화한다(main.py 의 수집 시계).
"""

import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Collection, Document, IngestSource, utcnow
from app.stages.multimodal import ingest as mm_ingest
from app.stages.rag import parsers, service


class SourceError(ValueError):
    pass


def allowed_roots() -> list[Path]:
    st = get_settings()
    roots = [Path(r) for r in st.ingest_roots] or [st.inbox_dir]
    return [r.resolve() for r in roots]


def check_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not any(p == r or p.is_relative_to(r) for r in allowed_roots()):
        raise SourceError(f"허용된 폴더(INGEST_ROOTS: {', '.join(str(r) for r in allowed_roots())}) 밖입니다.")
    if not p.is_dir():
        raise SourceError(f"폴더가 없습니다: {p}")
    return p


def supported(name: str) -> bool:
    return Path(name).suffix.lower() in parsers.SUPPORTED or bool(mm_ingest.kind_of(name))


def scan(src: IngestSource) -> list[Path]:
    root = check_path(src.path)
    pattern = src.pattern or "*"
    return sorted(p for p in root.rglob(pattern) if p.is_file() and supported(p.name) and not p.name.startswith(("~$", ".")))


def sync(db: Session, src: IngestSource) -> dict[str, Any]:
    col = db.get(Collection, src.collection_id)
    root = check_path(src.path)
    files = scan(src)
    mine = {(d.meta or {}).get("source_path"): d for d in db.scalars(select(Document).where(Document.collection_id == col.id))
            if (d.meta or {}).get("source_id") == src.id}  # fmt: skip
    stats: dict[str, Any] = {"new": 0, "changed": 0, "deleted": 0, "unchanged": 0, "skipped": []}
    seen = {f.relative_to(root).as_posix() for f in files}
    # 사라진 파일의 문서를 먼저 지운다 — 이름만 바뀐 파일(내용 같음)이 '이미 있는 문서'로 건너뛰어진 뒤
    # 옛 문서까지 지워져 내용이 통째로 사라지는 일을 막으려고(지우고 나서 넣으면 새 이름으로 다시 들어간다)
    for rel, d in mine.items():
        if rel not in seen:
            service.delete_document(db, d)
            stats["deleted"] += 1
    for f in files:
        rel = f.relative_to(root).as_posix()
        data = f.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        old = mine.get(rel)
        if old is not None and old.sha256 == sha:
            stats["unchanged"] += 1
            continue
        if old is not None:  # 내용이 바뀐 파일 — 옛 문서(청크 · 벡터 포함)를 지우고 새로 넣는다
            service.delete_document(db, old)
        ingest = mm_ingest.ingest if mm_ingest.kind_of(f.name) else service.ingest
        doc, msg = ingest(db, col, f.name, data)
        if doc is None:
            stats["skipped"].append({"file": rel, "reason": msg})
            continue
        doc.meta = dict(doc.meta or {}) | {
            "source_id": src.id,
            "source_path": rel,
            "source_mtime": f.stat().st_mtime,
            "source_kind": src.kind,
        }
        db.commit()
        stats["changed" if old is not None else "new"] += 1
    src.last_run_at = utcnow()
    src.last_stats = stats | {"n_files": len(files)}
    db.commit()
    return src.last_stats


def due(db: Session) -> list[IngestSource]:
    """주기가 된 소스 — interval_min 이 0 이면 손으로만."""
    now = utcnow()
    out = []
    for s in db.scalars(select(IngestSource).where(IngestSource.enabled.is_(True), IngestSource.interval_min > 0)):
        if s.last_run_at is None or s.last_run_at + timedelta(minutes=s.interval_min) <= now:
            out.append(s)
    return out


def out(s: IngestSource) -> dict[str, Any]:
    return {"id": s.id, "collection_id": s.collection_id, "kind": s.kind, "path": s.path, "pattern": s.pattern, "interval_min": s.interval_min,
            "enabled": s.enabled, "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None, "last_stats": s.last_stats}  # fmt: skip
