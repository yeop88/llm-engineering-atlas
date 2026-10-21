"""ED5 서버와 동기화 · 업데이트: 기기의 판 → 최신 판 증분(바뀐 · 새 문서의 청크만 + 지울 청크 번호), 기기 버전 관리.

증분 = 두 판 manifest 의 문서별 sha256 비교. 모델 · 정밀도 · 청크 세트가 바뀌면 벡터 공간이나 눈금이 달라 증분으로 섞을 수 없어
전체를 다시 받는다(full). 기기가 증분을 적용한 결과의 지문(pack_hash)이 서버 최신 판 지문과 같은지 서버에서 미리 맞춰 본다 —
동기화가 '맞게 됐다'를 기기 신고가 아니라 계산으로 확인하려고.

기기 버전 관리: 기기마다 받은 판과 마지막 동기화를 남겨 '낡은 자료로 답하는 기기'(판이 뒤처짐 · 오래 연결 안 됨)를 찾는다 —
같은 질문에 기기마다 다른 답이 나오는 원인이다.
"""

from typing import Any

import numpy as np

from app.core.db import EdgeDevice, utcnow
from app.stages.edge import pack as pk


def delta(name: str, from_version: int | None, to_version: int | None = None, with_content: bool = False) -> dict[str, Any]:
    new = pk.load(name, to_version)
    nm = new["manifest"]
    if not from_version:
        return _full(new, "기기에 팩이 없음", with_content)
    old_p = pk.load(name, from_version)
    old = old_p["manifest"]
    if (old["model"], old["precision"], old["chunk_set_id"]) != (nm["model"], nm["precision"], nm["chunk_set_id"]):
        return _full(new, "모델 · 정밀도 · 청크 세트가 바뀜 — 벡터를 섞을 수 없어 전체", with_content)
    od, nd = old["docs"], nm["docs"]
    added = [d for d in nd if d not in od]
    changed = [d for d in nd if d in od and od[d] != nd[d]]
    removed = [d for d in od if d not in nd]
    send_docs = {int(d) for d in added + changed}
    rows = [i for i, c in enumerate(new["chunks"]) if c["doc_id"] in send_docs]
    # 바뀐 문서는 옛 청크를 모두 지우고 새로 받는다(청크 번호가 일부 같아도) — 한 문서 안에 옛 · 새 청크가 섞이지 않게
    new_ids, gone = set(nm["chunk_ids"]), set(removed + changed)
    keep_old = [c["id"] for c in old_p["chunks"] if str(c["doc_id"]) not in gone and c["id"] in new_ids]
    remove_ids = sorted(set(old["chunk_ids"]) - set(keep_old))
    bpc = nm["bytes_per_chunk"]
    text_bytes = sum(len(new["chunks"][i]["text"].encode()) for i in rows)
    out = {"name": name, "from": from_version, "to": nm["version"], "mode": "delta", "added_docs": added, "changed_docs": changed,
           "removed_docs": removed, "send_chunks": len(rows), "remove_chunk_ids": remove_ids, "bytes": int(len(rows) * bpc + text_bytes),
           "full_bytes": nm["bytes"], "hash": nm["hash"]}  # fmt: skip
    # 기기가 할 일을 그대로 흉내: 옛 청크 중 남길 것 + 보낸 청크 → 지문 비교
    applied_ids = keep_old + [new["chunks"][i]["id"] for i in rows]
    applied_docs = {d: v for d, v in od.items() if d not in removed and d not in changed} | {d: nd[d] for d in added + changed}
    out["verified"] = pk.pack_hash(applied_docs, applied_ids, nm["model"], nm["precision"]) == nm["hash"]
    if with_content:
        out["chunks"] = [new["chunks"][i] for i in rows]
        out["arrays"] = {k: v.tolist() for k, v in pk.take(new["arrays"], np.array(rows, dtype=int)).items()} if rows else {}
    return out


def _full(p: dict[str, Any], reason: str, with_content: bool) -> dict[str, Any]:
    m = p["manifest"]
    out = {"name": m["name"], "from": None, "to": m["version"], "mode": "full", "reason": reason, "send_chunks": m["n_chunks"],
           "bytes": m["bytes"], "full_bytes": m["bytes"], "hash": m["hash"], "verified": True}  # fmt: skip
    if with_content:
        out["chunks"] = p["chunks"]
        out["arrays"] = {k: v.tolist() for k, v in p["arrays"].items()}
    return out


def device_status(d: EdgeDevice, latest: dict[str, int], stale_hours: float) -> dict[str, Any]:
    lv = latest.get(d.pack)
    age = (utcnow() - d.last_sync).total_seconds() / 3600 if d.last_sync else None
    flags = []
    if d.pack and lv is None:
        flags.append("서버에 없는 팩")
    elif lv and d.version < lv:
        flags.append(f"판 뒤처짐 v{d.version} → v{lv}")
    if age is None:
        flags.append("동기화 기록 없음")
    elif age > stale_hours:
        flags.append(f"{age:.0f}시간 동안 연결 안 됨")
    return {"id": d.id, "name": d.name, "profile": d.profile, "pack": d.pack, "version": d.version, "latest": lv,
            "last_sync": d.last_sync.isoformat() if d.last_sync else None, "age_hours": round(age, 1) if age is not None else None,
            "flags": flags, "ok": not flags}  # fmt: skip
