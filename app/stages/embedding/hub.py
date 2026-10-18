"""Hugging Face Hub 연동: 검색, 메타데이터 조회, 다운로드(진행률), 로컬 캐시 관리."""

import io
import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any

from huggingface_hub import HfApi, hf_hub_download, scan_cache_dir, snapshot_download
from huggingface_hub.errors import CacheNotFound, EntryNotFoundError
from tqdm import tqdm

from app.core.config import get_settings
from app.core.jobs import Job

log = logging.getLogger(__name__)

# sentence-transformers(PyTorch) 로딩에 필요 없는 대용량 포맷은 받지 않는다.
IGNORE_PATTERNS = [
    "onnx/*", "openvino/*", "coreml/*", "gguf/*", "*.onnx", "*.onnx_data", "*.gguf", "*.h5",
    "*.msgpack", "*.ot", "*.tflite", "*.mlmodel", "*.mlpackage/*", "tf_model*", "flax_model*", "rust_model*",
]  # fmt: skip
EMBEDDING_PIPELINES = ("sentence-similarity", "feature-extraction", "text-ranking")


def _api() -> HfApi:
    return HfApi(token=get_settings().hf_token or None)


def _iso(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""


def search(query: str = "", limit: int = 30, sort: str = "downloads", pipeline_tag: str | None = None) -> list[dict[str, Any]]:
    """임베딩 관련 파이프라인 태그로 Hub 모델을 검색한다."""
    api = _api()
    tags = [pipeline_tag] if pipeline_tag else list(EMBEDDING_PIPELINES)
    expand = ["downloads", "likes", "createdAt", "lastModified", "gated", "pipeline_tag", "library_name", "tags"]
    seen: dict[str, dict[str, Any]] = {}
    for tag in tags:
        for m in api.list_models(search=query or None, pipeline_tag=tag, sort=sort, limit=limit, expand=expand):
            if m.id in seen:
                continue
            tags_ = m.tags or []
            seen[m.id] = {
                "hf_id": m.id,
                "downloads": m.downloads or 0,
                "likes": m.likes or 0,
                "created_at": _iso(m.created_at),
                "last_modified": _iso(m.last_modified),
                "gated": bool(m.gated),
                "pipeline_tag": m.pipeline_tag,
                "library": m.library_name,
                "sentence_transformers": "sentence-transformers" in tags_ or m.library_name == "sentence-transformers",
                "license": next((t.split(":", 1)[1] for t in tags_ if t.startswith("license:")), ""),
            }
    key = {"downloads": "downloads", "likes": "likes", "created_at": "created_at", "last_modified": "last_modified"}.get(sort, "downloads")
    return sorted(seen.values(), key=lambda r: r[key], reverse=True)[:limit]


# 새 모델 후보를 찾는 Hub 질의: (설명, pipeline_tag, 태그 필터). 인기 급상승(trending) 순으로 받아 최근 공개 · 반응 있는 것만 남긴다.
DISCOVER_QUERIES = [
    ("한국어 임베딩", "sentence-similarity", "ko"),
    ("다국어 · 일반 임베딩", "sentence-similarity", None),
    ("특징 추출(멀티모달 포함)", "feature-extraction", None),
    ("한국어 리랭커", "text-ranking", "ko"),
    ("리랭커", "text-ranking", None),
]
_discover_cache: tuple[float, dict[str, Any], list[dict[str, Any]]] = (0.0, {}, [])


def discover(registered: set[str], excluded: set[str], days: int = 180, min_likes: int = 10, limit: int = 30,
             per_query: int = 60, force: bool = False) -> list[dict[str, Any]]:  # fmt: skip
    """카탈로그에 없는 새 임베딩 · 리랭커 후보. 카탈로그는 손으로 고른 목록이라 새 모델이 나와도 모르고 지나가기 쉬워서 둔다.

    자동으로 추가하지는 않는다 — 스펙(프롬프트 · 차원 · 라이선스)은 카탈로그 추가 규칙대로 사람이 Hub 설정 파일로 확인하고 가져온다.
    점수 = 좋아요(로그) + 최근일수록 가산 + 한국어 태그 가산. Hub 호출이 여러 번이라 1시간 캐시.
    """
    global _discover_cache
    import math
    import time as _t

    key = {"days": days, "min_likes": min_likes, "per_query": per_query}
    if not force and _t.time() - _discover_cache[0] < 3600 and _discover_cache[1] == key:
        rows = _discover_cache[2]
    else:
        api = _api()
        expand = ["downloads", "likes", "createdAt", "lastModified", "gated", "pipeline_tag", "library_name", "tags"]
        seen: dict[str, dict[str, Any]] = {}
        now = datetime.now(UTC)
        for label, tag, filt in DISCOVER_QUERIES:
            for m in api.list_models(pipeline_tag=tag, filter=filt, sort="trending_score", limit=per_query, expand=expand):
                if m.id in seen or not m.created_at:
                    continue
                tags_ = m.tags or []
                if "gguf" in tags_ or m.id.lower().endswith(("-gguf", "-onnx", "-mlx")) or "nvfp4" in m.id.lower():
                    continue  # PyTorch(sentence-transformers)로 못 올리는 변환본 — 원본 모델이 따로 있다
                age = (now - m.created_at).days
                if age > days or (m.likes or 0) < min_likes:
                    continue
                korean = "ko" in tags_ or "korean" in m.id.lower()
                seen[m.id] = {
                    "hf_id": m.id, "found_by": label, "pipeline_tag": m.pipeline_tag, "likes": m.likes or 0,
                    "downloads": m.downloads or 0, "created_at": _iso(m.created_at), "age_days": age, "korean": korean,
                    "gated": bool(m.gated), "sentence_transformers": "sentence-transformers" in tags_ or m.library_name == "sentence-transformers",
                    "license": next((t.split(":", 1)[1] for t in tags_ if t.startswith("license:")), ""),
                    "score": round(math.log1p(m.likes or 0) + 2 * max(0.0, 1 - age / days) + (1.5 if korean else 0), 3),
                }  # fmt: skip
        rows = sorted(seen.values(), key=lambda r: r["score"], reverse=True)
        _discover_cache = (_t.time(), key, rows)
    return [r for r in rows if r["hf_id"] not in registered and r["hf_id"] not in excluded][:limit]


def _read_json(repo_id: str, filename: str) -> dict[str, Any] | None:
    try:
        path = hf_hub_download(repo_id, filename, token=get_settings().hf_token or None)
    except EntryNotFoundError, OSError, ValueError:
        return None
    except Exception:  # gated, 네트워크 오류 등은 메타데이터 보강만 포기
        log.debug("config 파일 읽기 실패: %s/%s", repo_id, filename, exc_info=True)
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _format_params(n: int | None) -> str:
    if not n:
        return ""
    if n >= 1e9:
        return f"{n / 1e9:.1f}B"
    return f"{n / 1e6:.0f}M"


def model_metadata(repo_id: str) -> dict[str, Any]:
    """Hub 카드/설정 파일에서 카탈로그 필드를 최대한 채운다."""
    info = _api().model_info(
        repo_id,
        expand=[
            "downloads",
            "likes",
            "createdAt",
            "lastModified",
            "gated",
            "cardData",
            "safetensors",
            "pipeline_tag",
            "library_name",
            "tags",
            "siblings",
        ],
    )
    card = info.card_data.to_dict() if info.card_data else {}
    st_cfg = _read_json(repo_id, "config_sentence_transformers.json") or {}
    sb_cfg = _read_json(repo_id, "sentence_bert_config.json") or {}
    cfg = _read_json(repo_id, "config.json") or {}
    text_cfg = cfg.get("text_config", cfg)
    prompts: dict[str, str] = st_cfg.get("prompts") or {}

    license_ = card.get("license_name") or card.get("license") or ""
    lang = card.get("language")
    languages = (
        ("multilingual" if isinstance(lang, list) and len(lang) > 5 else ", ".join(lang)) if isinstance(lang, list) else (lang or "")
    )
    tags = info.tags or []
    modalities = ["text"]
    if (
        any(t in tags for t in ("image-feature-extraction", "image-text-to-text", "zero-shot-image-classification"))
        or "vision_config" in cfg
    ):
        modalities.append("image")
    if "audio_config" in cfg:
        modalities.append("audio")

    archs = cfg.get("architectures") or []
    is_reranker = info.pipeline_tag == "text-ranking" or any(a.endswith("ForSequenceClassification") for a in archs)

    def pick(*names: str) -> str:
        return next((n for n in names if n in prompts), "")

    return {
        "hf_id": info.id,
        "name": info.id.split("/")[-1],
        "kind": "reranker" if is_reranker else "embedding",
        "provider": info.id.split("/")[0],
        "release_date": info.created_at.date().isoformat() if info.created_at else "",
        "params": _format_params(info.safetensors.total if info.safetensors else None),
        "dim": None if is_reranker else text_cfg.get("hidden_size"),
        "max_seq_len": sb_cfg.get("max_seq_length") or text_cfg.get("max_position_embeddings"),
        "license": str(license_),
        "languages": languages,
        "modalities": modalities,
        "query_prompt": pick("query", "search_query", "SearchQuery", "Retrieval-query", "web_search_query", "retrieval.query"),
        "document_prompt": pick("document", "passage", "Document", "search_document", "Retrieval-document", "retrieval.passage"),
        "trust_remote_code": bool(cfg.get("auto_map")),
        "gated": bool(info.gated),
        "hub_downloads": info.downloads,
        "hub_likes": info.likes,
        "hub_last_modified": _iso(info.last_modified),
        "prompts": prompts,
        "pipeline_tag": info.pipeline_tag,
        "library": info.library_name,
        "sentence_transformers": "sentence-transformers" in tags,
        "size_bytes": sum((s.size or 0) for s in (info.siblings or [])),
    }


# ── 로컬 캐시 ────────────────────────────────────────────────────────────────
_cache_lock = threading.Lock()
_cache_snapshot: tuple[float, dict[str, dict[str, Any]]] = (0.0, {})


def cache_status(force: bool = False) -> dict[str, dict[str, Any]]:
    """repo_id → {size_bytes, revisions, last_modified}. 스캔 비용 때문에 5초간 캐시."""
    global _cache_snapshot
    now = datetime.now(UTC).timestamp()
    with _cache_lock:
        if not force and now - _cache_snapshot[0] < 5:
            return _cache_snapshot[1]
        try:
            info = scan_cache_dir()
        except CacheNotFound:
            result: dict[str, dict[str, Any]] = {}
        else:
            result = {
                r.repo_id: {
                    "size_bytes": r.size_on_disk,
                    "revisions": [rev.commit_hash for rev in r.revisions],
                    "nb_files": r.nb_files,
                    "last_modified": datetime.fromtimestamp(r.last_modified, UTC).isoformat(),
                }
                for r in info.repos
                if r.repo_type == "model"
            }
        _cache_snapshot = (now, result)
        return result


def delete_cache(repo_id: str) -> int:
    try:
        info = scan_cache_dir()
    except CacheNotFound:
        return 0
    hashes = [rev.commit_hash for r in info.repos if r.repo_id == repo_id and r.repo_type == "model" for rev in r.revisions]
    if not hashes:
        return 0
    strategy = info.delete_revisions(*hashes)
    freed = strategy.expected_freed_size
    strategy.execute()
    cache_status(force=True)
    return freed


def _ignore_patterns_for(repo_id: str) -> list[str]:
    files = [s.rfilename for s in (_api().model_info(repo_id, files_metadata=False).siblings or [])]
    patterns = list(IGNORE_PATTERNS)
    if any(f.endswith(".safetensors") for f in files):
        patterns += ["*.bin", "*.pt", "*.pth"]  # safetensors 가 있으면 PyTorch pickle 가중치는 생략
    return patterns


def _progress_class(job: Job, total: int) -> type[tqdm]:
    """snapshot_download 의 바이트 진행률 바(tqdm)를 가로채 작업 진행률로 반영한다."""

    class JobProgress(tqdm):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["file"] = io.StringIO()  # 콘솔 출력 억제
            kwargs["disable"] = False
            super().__init__(*args, **kwargs)

        def update(self, n: float | None = 1) -> bool | None:
            result = super().update(n)
            if self.unit == "B" and total:
                done = min(self.n, total)
                job.progress = max(job.progress, min(0.99, done / total))
                job.message = f"{job.progress * total / 2**20:,.0f} / {total / 2**20:,.0f} MB"
            return result

    return JobProgress


def download(repo_id: str, job: Job) -> dict[str, Any]:
    """dry-run 으로 받을 파일을 확인한 뒤 snapshot_download 를 실행한다."""
    token = get_settings().hf_token or None
    job.update(0.0, "파일 목록 확인 중")
    ignore = _ignore_patterns_for(repo_id)
    plan = snapshot_download(repo_id, ignore_patterns=ignore, token=token, dry_run=True)
    pending = [f for f in plan if f.will_download]
    total = sum(f.file_size or 0 for f in pending)
    if not pending:
        job.update(1.0, "이미 모두 받아져 있습니다")
        return {"repo_id": repo_id, "downloaded_bytes": 0, "files": 0}

    job.update(0.0, f"다운로드 시작 ({len(pending)}개 파일, {total / 2**20:,.0f} MB)")
    path = snapshot_download(repo_id, ignore_patterns=ignore, token=token, tqdm_class=_progress_class(job, total))
    cache_status(force=True)
    job.update(1.0, "완료")
    return {"repo_id": repo_id, "path": path, "downloaded_bytes": total, "files": len(pending)}
