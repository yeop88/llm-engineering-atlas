"""벡터 저장소 공통 인터페이스. 모든 점수는 코사인 유사도(클수록 가까움)로 통일한다."""

import re
from abc import ABC, abstractmethod
from typing import Any

import numpy as np


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
