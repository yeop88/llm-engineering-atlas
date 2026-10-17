"""콘텐츠 추천: 좋아요/싫어요 아이템과 관심사 문장으로 취향 벡터를 만들고, 비슷하면서도 서로 겹치지 않는 아이템을 고른다.

profile = normalize( mean(좋아요) − β·mean(싫어요) + γ·관심사 )
선택은 MMR: argmax  λ·sim(item, profile) − (1−λ)·max sim(item, 이미 고른 것)
"""

from typing import Any

import numpy as np

from app.stages.apps.common import AppError, Item, item_out, normalize


def recommend(
    items: list[Item],
    vectors: np.ndarray,
    liked: list[str],
    disliked: list[str] | None = None,
    interest_vec: np.ndarray | None = None,
    top_k: int = 10,
    diversity: float = 0.3,
    negative_weight: float = 0.5,
    interest_weight: float = 1.0,
    exclude_seen: bool = True,
) -> dict[str, Any]:
    keys = [it.key for it in items]
    pos = [keys.index(k) for k in liked if k in keys]
    neg = [keys.index(k) for k in (disliked or []) if k in keys]
    if not pos and interest_vec is None:
        raise AppError("좋아요한 아이템이나 관심사 문장이 하나 이상 필요합니다.")
    v = normalize(vectors)
    profile = np.zeros(v.shape[1], dtype=np.float32)
    if pos:
        profile += v[pos].mean(axis=0)
    if neg:
        profile -= negative_weight * v[neg].mean(axis=0)
    if interest_vec is not None:
        profile += interest_weight * normalize(interest_vec.reshape(-1))
    profile = normalize(profile)

    relevance = v @ profile
    seen = set(pos) | set(neg) if exclude_seen else set()
    candidates = [i for i in np.argsort(-relevance) if i not in seen]
    lam = 1.0 - float(diversity)
    chosen: list[int] = []
    while candidates and len(chosen) < top_k:
        if chosen:
            redundancy = (v[candidates] @ v[chosen].T).max(axis=1)
            scores = lam * relevance[candidates] - (1 - lam) * redundancy
            best = candidates[int(np.argmax(scores))]
        else:
            best = candidates[0]
        chosen.append(best)
        candidates.remove(best)

    out = []
    for rank, i in enumerate(chosen, start=1):
        because = None
        if pos:  # 추천 이유: 가장 비슷한 좋아요 아이템
            sims = v[pos] @ v[i]
            j = int(np.argmax(sims))
            because = {"key": items[pos[j]].key, "similarity": round(float(sims[j]), 4), "text": items[pos[j]].text[:80]}
        out.append(item_out(items[i], rank=rank, score=round(float(relevance[i]), 4), because=because))
    return {
        "results": out,
        "profile_size": {"liked": len(pos), "disliked": len(neg), "interest": interest_vec is not None},
        "coverage": round(float(np.mean([relevance[i] for i in chosen])) if chosen else 0.0, 4),
        "intra_similarity": round(
            float(np.mean((v[chosen] @ v[chosen].T)[np.triu_indices(len(chosen), 1)])) if len(chosen) > 1 else 0.0, 4
        ),
    }
