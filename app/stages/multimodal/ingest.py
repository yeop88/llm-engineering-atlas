"""이미지 · 영상 수집: 파일을 저장하고, 영상은 프레임을 뽑아 RAG 컬렉션의 '미디어 문서'로 만든다.

설계 이유
- 별도 저장소를 만들지 않고 RAG 컬렉션의 문서로 넣는다. 청크 하나 = 이미지 한 장(또는 프레임 한 장)으로 두면
  청크 세트 → 벡터 인덱스 → 검색 비교 · 평가 세트 · 이력을 그대로 쓸 수 있고, 같은 컬렉션에서 글과 그림을
  함께 찾을 수 있다. 문서 meta["media_items"] 만 약속하면 RAG 쪽은 이 모듈을 몰라도 된다(단계 의존 방향 유지).
- 영상은 장면 검색이 목적이므로 일정 간격으로 프레임을 뽑되, 화면이 거의 그대로인 프레임은 버린다.
  정지 화면이 길면 같은 그림이 검색 결과를 도배하고 인코딩 시간만 늘기 때문이다.
- 영상 디코딩은 PyAV(FFmpeg 내장 휠)로 한다. 시스템에 ffmpeg 를 따로 설치하지 않아도 되게 하려고.
"""

import hashlib
import io
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import media_store
from app.core.config import get_settings
from app.core.db import Collection, Document

log = logging.getLogger(__name__)

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
FRAME_MAX_SIDE = 768  # 임베딩 모델 입력(대개 224~896px)보다 크게 저장해 봐야 디스크 · 인코딩 시간만 든다
SCENE_DIFF = 6.0  # 16×16 흑백 축소본의 평균 밝기 차(0~255)가 이보다 작으면 같은 장면으로 보고 버린다


def kind_of(filename: str) -> str | None:
    ext = Path(filename).suffix.lower()
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else None


def label_for(filename: str) -> str:
    """파일 이름을 검색 가능한 글로: '빨간_사과-01.jpg' → '빨간 사과 01'. BM25 · 결과 표시 · 텍스트 전용 모델 색인에 쓴다."""
    return re.sub(r"[_\-.]+", " ", Path(filename).stem).strip() or filename


def _fmt_t(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m // 60}:{m % 60:02d}:{s:02d}" if m >= 60 else f"{m}:{s:02d}"


def _thumb(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("L").resize((16, 16)), dtype=np.float32)


def extract_frames(data: bytes, interval: float, max_frames: int) -> tuple[list[tuple[float, Image.Image]], dict[str, Any]]:
    """→ ([(초, 프레임 이미지)], 정보). interval 초마다 한 장, 직전에 남긴 프레임과 거의 같으면 건너뛴다."""
    import av  # 영상이 없으면 불러올 필요가 없는 무거운 모듈이라 여기서 import

    frames: list[tuple[float, Image.Image]] = []
    skipped_same = 0
    try:
        with av.open(io.BytesIO(data)) as container:
            if not container.streams.video:
                raise media_store.MediaError("영상 스트림이 없습니다.")
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            duration = float(container.duration / av.time_base) if container.duration else None
            next_t, last = 0.0, None
            # 순서대로 디코딩한다. 구간마다 seek 하면 긴 영상에서 빠르지만, 키프레임이 드문 영상에서 시각이 어긋나
            # 같은 프레임을 여러 번 얻는 문제가 있다. 업로드 크기 제한(MAX_UPLOAD_MB) 안의 영상이면 이 편이 단순하고 정확하다.
            for frame in container.decode(stream):
                t = float(frame.time) if frame.time is not None else next_t
                if t + 1e-6 < next_t:
                    continue
                next_t = t + interval
                im = frame.to_image()
                im.thumbnail((FRAME_MAX_SIDE, FRAME_MAX_SIDE))
                th = _thumb(im)
                if last is not None and float(np.abs(th - last).mean()) < SCENE_DIFF:
                    skipped_same += 1
                    continue
                last = th
                frames.append((t, im))
                if len(frames) >= max_frames:
                    break
    except media_store.MediaError:
        raise
    except Exception as exc:  # 손상 · 미지원 코덱 등 — 사용자에게 이유를 보여 준다
        raise media_store.MediaError(f"영상을 읽을 수 없습니다 ({type(exc).__name__}: {exc})") from exc
    if not frames:
        raise media_store.MediaError("영상에서 프레임을 하나도 얻지 못했습니다.")
    info = {"duration": round(duration, 2) if duration else None, "interval": interval, "skipped_same_scene": skipped_same,
            "truncated": len(frames) >= max_frames}  # fmt: skip
    return frames, info


def ingest(db: Session, collection: Collection, filename: str, data: bytes) -> tuple[Document | None, str]:
    """반환: (문서, 메시지) — rag.service.ingest 와 같은 약속(중복 · 오류면 (None, 이유))."""
    s = get_settings()
    kind = kind_of(filename)
    if kind is None:
        return None, "이미지 · 영상 파일이 아닙니다."
    if len(data) > s.max_upload_mb * 2**20:
        return None, f"파일이 너무 큽니다 ({len(data) / 2**20:.1f}MB > {s.max_upload_mb}MB)"
    sha = hashlib.sha256(data).hexdigest()
    dup = db.scalar(select(Document).where(Document.collection_id == collection.id, Document.sha256 == sha))
    if dup:
        return None, f"이미 있는 문서입니다 (#{dup.id} {dup.filename})"

    label = label_for(filename)
    # 디코딩 · 검증을 DB 에 넣기 전에 끝낸다 — 깨진 파일이 빈 문서로 남지 않게.
    try:
        if kind == "image":
            with Image.open(io.BytesIO(data)) as im:
                im.load()
                width, height = im.size
            frames, info = [], {"width": width, "height": height}
        else:
            frames, info = extract_frames(data, s.video_frame_interval, s.video_max_frames)
    except (UnidentifiedImageError, OSError) as exc:
        return None, f"이미지를 열 수 없습니다 ({exc})"
    except media_store.MediaError as exc:
        return None, str(exc)

    doc = Document(
        collection_id=collection.id, filename=filename[:500], title=label, mime=f"{kind}/{Path(filename).suffix.lower().lstrip('.')}",
        size_bytes=len(data), sha256=sha, n_chars=0, pages=[], meta={"page_kind": "media"},
    )  # fmt: skip
    db.add(doc)
    db.flush()  # 파일 폴더 이름에 문서 id 가 필요하다
    folder = media_store.doc_dir(doc.id)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        original = folder / f"original{Path(filename).suffix.lower()}"
        original.write_bytes(data)
        if kind == "image":
            items = [{"path": media_store.rel(original), "t": None, "label": label}]
        else:
            items = []
            for i, (t, im) in enumerate(frames):
                p = folder / f"frame-{i:04d}.jpg"
                im.save(p, "JPEG", quality=88)
                items.append({"path": media_store.rel(p), "t": round(t, 2), "label": f"{label} {_fmt_t(t)}"})
        # pages 에는 라벨을 넣는다 — 문서 미리보기 · 글자 수 등 기존 화면이 그대로 동작하게.
        doc.pages = [it["label"] for it in items]
        doc.n_chars = sum(len(x) for x in doc.pages)
        doc.meta = {"page_kind": "media", "media": {"kind": kind, "path": media_store.rel(original), **info}, "media_items": items}
        db.commit()
    except Exception:
        db.rollback()
        media_store.remove_document_media(doc.id)
        raise
    msg = ""
    if kind == "video":
        msg = f"프레임 {len(items)}장 추출 (같은 장면 {info['skipped_same_scene']}장 제외{', 최대 장수에서 잘림' if info['truncated'] else ''})"
    return doc, msg
