"""미디어 파일(이미지 · 영상 프레임) 저장 위치와 안전한 경로 해석.

이미지 · 영상 문서는 RAG 컬렉션의 문서로 들어가고(청크 하나 = 이미지 한 장 또는 영상 프레임 한 장),
색인 · 검색 · 화면이 같은 파일을 읽는다. 여러 단계가 함께 쓰므로 core 에 둔다.
DB 에는 media_dir 기준 상대 경로만 저장한다 — 데이터 폴더를 옮겨도(DATA_DIR) 경로가 깨지지 않게.
"""

import shutil
from pathlib import Path

from PIL import Image

from app.core.config import get_settings


class MediaError(ValueError):
    pass


def doc_dir(doc_id: int) -> Path:
    return get_settings().media_dir / f"doc-{doc_id}"


def rel(path: Path) -> str:
    return path.relative_to(get_settings().media_dir).as_posix()


def resolve(rel_path: str) -> Path:
    """상대 경로 → 실제 경로. '..' 등으로 media_dir 밖을 가리키면 거부한다(파일 제공 API 가 임의 파일을 내주지 않도록)."""
    root = get_settings().media_dir.resolve()
    p = (root / rel_path).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise MediaError("미디어 파일을 찾을 수 없습니다.")
    return p


def open_image(rel_path: str) -> Image.Image:
    with Image.open(resolve(rel_path)) as im:
        return im.convert("RGB")  # 투명도 · 팔레트 이미지도 모델 입력 형식(RGB)으로 맞춘다


def remove_document_media(doc_id: int) -> None:
    shutil.rmtree(doc_dir(doc_id), ignore_errors=True)


# ── 문서 원본 ─────────────────────────────────────────────────────────────
# 0.x 까지는 글만 뽑아 두고 원본을 버렸다. 문서 처리 맵(OCR · 표 · 그림 다시 뽑기, 처리 방법을 바꿔 다시 처리)에는 원본이 필요해
# 업로드할 때 내용 해시 이름으로 남긴다. 같은 파일을 여러 컬렉션에 올려도 한 벌만 저장한다.
def original_path(sha256: str, filename: str) -> Path:
    ext = Path(filename).suffix.lower()[:10]
    return get_settings().upload_dir / sha256[:2] / f"{sha256}{ext}"


def save_original(sha256: str, filename: str, data: bytes) -> str:
    """원본 저장 → upload_dir 기준 상대 경로."""
    p = original_path(sha256, filename)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return p.relative_to(get_settings().upload_dir).as_posix()


def read_original(rel_path: str) -> bytes:
    root = get_settings().upload_dir.resolve()
    p = (root / rel_path).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise MediaError("원본 파일이 없습니다 — 원본 저장 전에 올린 문서는 다시 올려야 합니다.")
    return p.read_bytes()


def remove_original(rel_path: str) -> None:
    root = get_settings().upload_dir.resolve()
    p = (root / rel_path).resolve()
    if p.is_relative_to(root) and p.is_file():
        p.unlink()
