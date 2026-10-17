"""SentenceTransformer 모델 로딩/언로딩(LRU)과 역할(query/document)별 인코딩."""

import copy
import gc
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings
from app.core.db import EmbeddingModel
from app.core.runtime import resolve_device, resolve_dtype

log = logging.getLogger(__name__)

Role = Literal["query", "document", "plain"]


@dataclass(frozen=True)
class ModelSpec:
    """DB 행의 스냅샷. 로딩/인코딩에 필요한 값만 담는다(스레드 간 안전하게 공유)."""

    id: int
    hf_id: str
    modalities: tuple[str, ...]
    trust_remote_code: bool
    load_kwargs: dict[str, Any]
    multimodal_load_kwargs: dict[str, Any]
    query_prompt: str
    document_prompt: str
    query_prefix: str
    document_prefix: str
    query_kwargs: dict[str, Any]
    document_kwargs: dict[str, Any]
    max_seq_len: int | None = None
    kind: str = "embedding"  # embedding | reranker

    @classmethod
    def from_row(cls, row: EmbeddingModel) -> ModelSpec:
        return cls(
            id=row.id,
            hf_id=row.hf_id,
            modalities=tuple(row.modalities or ["text"]),
            trust_remote_code=row.trust_remote_code,
            load_kwargs=copy.deepcopy(row.load_kwargs or {}),
            multimodal_load_kwargs=copy.deepcopy(row.multimodal_load_kwargs or {}),
            query_prompt=row.query_prompt or "",
            document_prompt=row.document_prompt or "",
            query_prefix=row.query_prefix or "",
            document_prefix=row.document_prefix or "",
            query_kwargs=copy.deepcopy(row.query_kwargs or {}),
            document_kwargs=copy.deepcopy(row.document_kwargs or {}),
            max_seq_len=row.max_seq_len,
            kind=row.kind or "embedding",
        )

    @property
    def is_multimodal(self) -> bool:
        return any(m != "text" for m in self.modalities)

    @property
    def is_reranker(self) -> bool:
        return self.kind == "reranker"

    def profile_for(self, multimodal: bool) -> str:
        if self.is_reranker:
            return "reranker"
        return "multimodal" if multimodal and self.is_multimodal else "text"


@dataclass
class LoadedModel:
    key: str
    spec: ModelSpec
    profile: str
    model: Any  # SentenceTransformer 또는 CrossEncoder(리랭커)
    device: str
    dtype: str
    load_seconds: float
    loaded_at: datetime
    last_used: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def dim(self) -> int | None:
        fn = getattr(self.model, "get_embedding_dimension", None)
        return fn() if fn else None

    @property
    def prompts(self) -> dict[str, str]:
        return dict(getattr(self.model, "prompts", None) or {})

    def summary(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "model_id": self.spec.id,
            "hf_id": self.spec.hf_id,
            "profile": self.profile,
            "device": self.device,
            "dtype": self.dtype,
            "dim": self.dim,
            "kind": self.spec.kind,
            "max_seq_length": getattr(self.model, "max_seq_length", None) or getattr(self.model, "max_length", None),
            "prompts": list(self.prompts),
            "load_seconds": round(self.load_seconds, 2),
            "loaded_at": self.loaded_at.isoformat(),
            "last_used": datetime.fromtimestamp(self.last_used, UTC).isoformat(),
        }


# 작업별로 모델 설정(config_sentence_transformers.json)에서 찾아볼 프롬프트 이름 (앞쪽 우선)
TASK_PROMPTS = {
    "classification": ("Classification", "classification"),
    "clustering": ("Clustering", "clustering"),
    "similarity": ("SentenceSimilarity", "STS", "sts_query", "sts"),
}


def task_prompt_name(prompts: dict[str, str], task: str) -> str | None:
    return next((n for n in TASK_PROMPTS.get(task, ()) if n in prompts), None)


@dataclass
class EncodeResult:
    embeddings: np.ndarray
    seconds: float
    applied: dict[str, Any]
    warnings: list[str]


class ModelManager:
    def __init__(self, max_loaded: int):
        self.max_loaded = max(1, max_loaded)
        self._models: OrderedDict[str, LoadedModel] = OrderedDict()
        self._lock = threading.RLock()
        self._load_locks: dict[str, threading.Lock] = {}
        self.errors: dict[str, str] = {}

    @staticmethod
    def key_for(spec: ModelSpec, multimodal: bool = False) -> str:
        return f"{spec.hf_id}::{spec.profile_for(multimodal)}"

    # ── 조회 ────────────────────────────────────────────────────────────────
    def loaded(self) -> list[LoadedModel]:
        with self._lock:
            return list(self._models.values())

    def is_loaded(self, hf_id: str) -> list[str]:
        with self._lock:
            return [lm.profile for lm in self._models.values() if lm.spec.hf_id == hf_id]

    # ── 로딩 ────────────────────────────────────────────────────────────────
    def get(self, spec: ModelSpec, multimodal: bool = False) -> LoadedModel:
        key = self.key_for(spec, multimodal)
        with self._lock:
            lm = self._models.get(key)
            if lm is not None and lm.spec == spec:
                self._models.move_to_end(key)
                lm.last_used = time.time()
                return lm
            load_lock = self._load_locks.setdefault(key, threading.Lock())

        with load_lock:  # 같은 모델을 동시에 두 번 로드하지 않도록
            with self._lock:
                lm = self._models.get(key)
                if lm is not None and lm.spec == spec:
                    return lm
                if lm is not None:  # 설정이 바뀌었으면 다시 로드
                    self._drop(key)
            lm = self._load(spec, multimodal, key)
            with self._lock:
                self._models[key] = lm
                self._evict()
            return lm

    def _load(self, spec: ModelSpec, multimodal: bool, key: str) -> LoadedModel:
        settings = get_settings()
        device = resolve_device()
        profile = spec.profile_for(multimodal)
        kwargs = copy.deepcopy(spec.multimodal_load_kwargs if profile == "multimodal" else spec.load_kwargs)
        model_kwargs = dict(kwargs.pop("model_kwargs", {}) or {})
        dtype = resolve_dtype(device)
        model_kwargs.setdefault("dtype", dtype)

        log.info("모델 로드 시작: %s (%s, %s, %s)", spec.hf_id, profile, device, dtype)
        started = time.perf_counter()
        common = {
            "device": device,
            "trust_remote_code": spec.trust_remote_code,
            "token": settings.hf_token or None,
            "model_kwargs": model_kwargs,
        }
        try:
            if spec.is_reranker:
                from sentence_transformers import CrossEncoder

                # 긴 컨텍스트 리랭커(8K~40K)를 그대로 쓰면 메모리·시간이 폭증하므로 기본 길이를 제한
                kwargs.setdefault("max_length", min(spec.max_seq_len or settings.reranker_max_length, settings.reranker_max_length))
                model = CrossEncoder(spec.hf_id, **common, **kwargs)
            else:
                model = SentenceTransformer(spec.hf_id, **common, **kwargs)
        except Exception as exc:
            self.errors[key] = f"{type(exc).__name__}: {exc}"
            raise
        self.errors.pop(key, None)
        # 토크나이저에 model_max_length 가 없으면 사실상 무한대로 잡히므로 카탈로그 값으로 제한
        current = getattr(model, "max_seq_length", None)
        if not spec.is_reranker and spec.max_seq_len and (current is None or current > 1_000_000):
            model.max_seq_length = spec.max_seq_len
        elapsed = time.perf_counter() - started
        log.info("모델 로드 완료: %s (%.1fs)", spec.hf_id, elapsed)
        return LoadedModel(
            key=key,
            spec=spec,
            profile=profile,
            model=model,
            device=device,
            dtype=str(model_kwargs["dtype"]).replace("torch.", ""),
            load_seconds=elapsed,
            loaded_at=datetime.now(UTC),
        )

    def _evict(self) -> None:
        while len(self._models) > self.max_loaded:
            old_key = next(iter(self._models))
            log.info("LRU 언로드: %s", old_key)
            self._drop(old_key)

    def _drop(self, key: str) -> None:
        lm = self._models.pop(key, None)
        if lm is None:
            return
        del lm
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def unload(self, hf_id: str) -> int:
        with self._lock:
            keys = [k for k, lm in self._models.items() if lm.spec.hf_id == hf_id]
            for k in keys:
                self._drop(k)
            return len(keys)

    def unload_all(self) -> int:
        with self._lock:
            keys = list(self._models)
            for k in keys:
                self._drop(k)
            return len(keys)

    # ── 리랭킹 ──────────────────────────────────────────────────────────────
    def rerank(self, lm: LoadedModel, query: str, documents: list[str], batch_size: int | None = None) -> tuple[np.ndarray, float]:
        """(질의, 문서) 쌍의 관련도 점수. 클수록 관련 있음 (척도는 모델마다 다름)."""
        if not lm.spec.is_reranker:
            raise ValueError(f"{lm.spec.hf_id} 는 리랭커가 아닙니다.")
        if not documents:
            return np.zeros(0, dtype=np.float32), 0.0
        lm.last_used = time.time()
        started = time.perf_counter()
        with lm.lock, torch.inference_mode():
            scores = lm.model.predict(
                [(query, d) for d in documents], batch_size=batch_size or get_settings().default_batch_size, show_progress_bar=False
            )
        scores = np.asarray(scores, dtype=np.float32).reshape(len(documents), -1)
        if scores.shape[1] > 1:  # 다중 레이블 모델은 마지막(관련) 레이블 사용
            scores = scores[:, -1:]
        return scores[:, 0], time.perf_counter() - started

    # ── 인코딩 ──────────────────────────────────────────────────────────────
    def encode(
        self,
        lm: LoadedModel,
        inputs: list[Any],
        role: Role = "plain",
        *,
        truncate_dim: int | None = None,
        normalize: bool = True,
        batch_size: int | None = None,
        task: str | None = None,
    ) -> EncodeResult:
        """task(classification | clustering | similarity)를 주면 모델에 그 작업용 프롬프트가 정의돼 있을 때 그것을 쓴다
        (예: EmbeddingGemma 의 Classification). 없으면 role 기준 프롬프트를 쓴다."""
        spec = lm.spec
        if spec.is_reranker:
            raise ValueError(f"{spec.hf_id} 는 리랭커라 임베딩을 만들 수 없습니다. 임베딩 모델을 선택하세요.")
        warnings: list[str] = []
        prompt_name = {"query": spec.query_prompt, "document": spec.document_prompt}.get(role, "")
        prefix = {"query": spec.query_prefix, "document": spec.document_prefix}.get(role, "")
        extra = copy.deepcopy({"query": spec.query_kwargs, "document": spec.document_kwargs}.get(role, {}))

        if task and (task_prompt := task_prompt_name(lm.prompts, task)):
            prompt_name, prefix, extra = task_prompt, "", {}

        kwargs: dict[str, Any] = {}
        if prompt_name:
            if prompt_name in lm.prompts:
                kwargs["prompt_name"] = prompt_name
            else:
                warnings.append(f"프롬프트 '{prompt_name}' 이(가) 모델에 없어 무시했습니다. 사용 가능: {list(lm.prompts) or '없음'}")
        if prefix:
            inputs = [prefix + x if isinstance(x, str) else x for x in inputs]

        dim = lm.dim
        if truncate_dim and dim and truncate_dim >= dim:
            truncate_dim = None
        lm.last_used = time.time()
        started = time.perf_counter()
        with lm.lock, torch.inference_mode():
            emb = lm.model.encode(
                inputs,
                batch_size=batch_size or get_settings().default_batch_size,
                normalize_embeddings=normalize,
                truncate_dim=truncate_dim or None,
                convert_to_numpy=True,
                show_progress_bar=False,
                **kwargs,
                **extra,
            )
        seconds = time.perf_counter() - started
        emb = np.asarray(emb, dtype=np.float32)
        if not np.isfinite(emb).all():
            warnings.append("임베딩에 NaN/Inf 가 포함되어 있습니다. dtype(float16 등) 설정을 확인하세요.")
        applied = {
            "role": role,
            "prompt_name": kwargs.get("prompt_name"),
            "prompt_text": lm.prompts.get(kwargs["prompt_name"]) if "prompt_name" in kwargs else None,
            "prefix": prefix or None,
            "extra_kwargs": extra or None,
            "truncate_dim": truncate_dim,
            "normalize": normalize,
        }
        return EncodeResult(embeddings=emb, seconds=seconds, applied=applied, warnings=warnings)

    def encode_images(
        self, lm: LoadedModel, images: list[Any], *, truncate_dim: int | None = None, batch_size: int | None = None
    ) -> EncodeResult:
        """이미지(PIL) 임베딩. 플레이그라운드와 RAG 이미지 · 영상 프레임 색인이 같은 경로를 쓰도록 여기 둔다.

        - 입력 형식이 모델마다 달라 두 가지를 차례로 시도한다: EmbeddingGemma 2 · Qwen3-VL 계열은 {"image": ...}
          딕셔너리, CLIP 계열은 PIL 이미지를 그대로 받는다. 어느 쪽인지 설정에 없으므로 실패하면 다음 형식으로.
        - 이미지에는 질의/문서 프롬프트를 붙이지 않는다. 프롬프트는 텍스트용이라, 이미지 입력에 붙이면 모델이 무시하거나 오류를 낸다.
        - truncate_dim 은 텍스트 청크와 같은 인덱스에 들어가므로 텍스트 인코딩과 똑같이 적용해야 한다.
        """
        if not lm.spec.is_multimodal:
            raise ValueError(f"{lm.spec.hf_id} 는 텍스트 전용 모델이라 이미지를 인코딩할 수 없습니다.")
        dim = lm.dim
        if truncate_dim and dim and truncate_dim >= dim:
            truncate_dim = None
        lm.last_used = time.time()
        started = time.perf_counter()
        errors = []
        for build in (lambda im: {"image": im}, lambda im: im):
            try:
                with lm.lock, torch.inference_mode():
                    emb = lm.model.encode(
                        [build(im) for im in images],
                        batch_size=batch_size or get_settings().default_batch_size,
                        normalize_embeddings=True,
                        truncate_dim=truncate_dim or None,
                        convert_to_numpy=True,
                        show_progress_bar=False,
                    )
                emb = np.asarray(emb, dtype=np.float32)
                warnings = [] if np.isfinite(emb).all() else ["임베딩에 NaN/Inf 가 포함되어 있습니다. dtype 설정을 확인하세요."]
                applied = {"role": "image", "truncate_dim": truncate_dim, "normalize": True}
                return EncodeResult(embeddings=emb, seconds=time.perf_counter() - started, applied=applied, warnings=warnings)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
        raise ValueError(f"{lm.spec.hf_id} 이미지 인코딩 실패: {' / '.join(errors)}")


_manager: ModelManager | None = None


def get_manager() -> ModelManager:
    global _manager
    if _manager is None:
        _manager = ModelManager(get_settings().max_loaded_models)
    return _manager
