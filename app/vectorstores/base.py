"""벡터 저장소 공통 인터페이스. 모든 점수는 코사인 유사도(클수록 가까움)로 통일한다.

검색 정확도 정책: 인덱스 벡터 수가 VECTOR_EXACT_MAX(기본 2만) 이하이면 근사 인덱스(HNSW)를 쓰지 않고 정확 검색을 한다.
이 앱은 검색 설정을 비교·평가하는 도구라서, 근사 검색의 누락이 평가 결과를 오염시키면 안 된다
(MariaDB HNSW 기본 탐색 폭에서 한 문서의 청크 묶음을 통째로 놓쳐 모델 순위가 뒤바뀐 적이 있다).
그보다 크면 근사 검색을 쓰되 탐색 폭을 VECTOR_EF_SEARCH(기본 200) 이상으로 넓힌다."""

import re
import threading
from abc import ABC, abstractmethod
from typing import Any

import numpy as np

from app.config import get_settings


class StoreUnavailable(RuntimeError):
    """설정이 없거나 서버에 연결할 수 없을 때."""


_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def check_name(name: str) -> str:
    # 테이블/컬렉션 이름은 SQL 에 직접 들어가므로 엄격하게 검사한다
    if not _NAME.fullmatch(name):
        raise ValueError(f"잘못된 벡터 컬렉션 이름: {name!r}")
    return name


class VectorStore(ABC):
    kind: str = ""
    _sizes: dict[str, int]
    _sizes_lock = threading.Lock()

    # ── 정확/근사 검색 선택 ──────────────────────────────────────────────────
    def use_exact(self, name: str) -> bool:
        """인덱스가 작으면 정확 검색. 벡터 수는 캐시하고 쓰기 때 무효화한다."""
        with self._sizes_lock:
            sizes = self.__dict__.setdefault("_sizes", {})
            n = sizes.get(name)
        if n is None:
            n = self.count(name)
            with self._sizes_lock:
                self._sizes[name] = n
        return n <= get_settings().vector_exact_max

    def forget_size(self, name: str) -> None:
        with self._sizes_lock:
            self.__dict__.setdefault("_sizes", {}).pop(name, None)

    @staticmethod
    def ef_search(top_k: int) -> int:
        return max(get_settings().vector_ef_search, int(top_k) * 4)

    @abstractmethod
    def ensure(self, name: str, dim: int) -> None:
        """컬렉션(테이블)이 없으면 만든다."""

    @abstractmethod
    def upsert(self, name: str, ids: list[int], vectors: np.ndarray, doc_ids: list[int]) -> None:
        """ids: 청크 id. doc_ids: 문서 필터용."""

    @abstractmethod
    def search(self, name: str, vector: np.ndarray, top_k: int, doc_ids: list[int] | None = None) -> list[tuple[int, float]]:
        """(청크 id, 코사인 유사도) 를 유사도 내림차순으로."""

    @abstractmethod
    def delete_ids(self, name: str, ids: list[int]) -> None: ...

    @abstractmethod
    def drop(self, name: str) -> None: ...

    @abstractmethod
    def count(self, name: str) -> int: ...

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """{"ok": bool, "version": str, "detail": str}"""
