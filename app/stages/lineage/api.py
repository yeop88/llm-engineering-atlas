"""기반 모델 계보 API (LN1~LN6). 읽은 모델은 data/lineage/models.json 에 쌓는다 — 같은 파일 · 저장소를 다시 읽으면 덮어쓴다."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.stages.bigmodel.gguf import GGUFError
from app.stages.edge import devices as edge_devices
from app.stages.lineage import graph, inspect
from app.stages.lineage.schemas import InspectIn

router = APIRouter(prefix="/api/lineage", tags=["lineage"])


def _data() -> Path:
    return get_settings().data_dir


@router.get("/models")
def models() -> dict:
    return {"models": list(inspect.load(_data()).values())}


@router.post("/scan")
def scan() -> dict:
    """가진 GGUF 를 모두 읽는다(투영기 파일 제외 — 모델 파일의 모달리티로 붙음)."""
    ms = inspect.load(_data())
    done, errors = [], []
    for f in edge_devices.gguf_files(get_settings().llm_models_dir):
        try:
            m = inspect.from_gguf(f["path"])
        except (GGUFError, OSError) as exc:
            errors.append({"file": f["name"], "error": str(exc)})
            continue
        ms[m["key"]] = m
        done.append(m["key"])
    inspect.save(_data(), ms)
    return {"read": done, "errors": errors, "total": len(ms)}


@router.post("/inspect")
def inspect_hf(body: InspectIn) -> dict:
    """HF 저장소: config.json + 모델 카드 메타(라이선스 · 기반 모델 · 용도 태그) — 가중치는 받지 않는다."""
    from huggingface_hub import hf_hub_download, model_info

    try:
        cfg = json.loads(Path(hf_hub_download(body.hf_id, "config.json")).read_text(encoding="utf-8"))
    except Exception as exc:  # 없는 저장소 · 승인이 필요한 저장소 · 오프라인
        raise HTTPException(400, f"{body.hf_id} 의 config.json 을 받지 못했습니다 ({type(exc).__name__})") from exc
    card = {}
    try:
        info = model_info(body.hf_id)
        cd = getattr(info, "card_data", None) or getattr(info, "cardData", None) or {}
        cd = cd.to_dict() if hasattr(cd, "to_dict") else dict(cd)
        card = {"license": cd.get("license"), "license_name": cd.get("license_name"), "license_link": cd.get("license_link"),
                "base_model": cd.get("base_model"), "pipeline_tag": getattr(info, "pipeline_tag", None)}  # fmt: skip
    except Exception:  # noqa: BLE001 — 카드가 없어도 config 만으로 읽는다(라이선스는 '없음' 으로 표시돼 확인 필요가 된다)
        card = {}
    try:
        m = inspect.from_hf(body.hf_id, cfg, card)
    except KeyError as exc:
        raise HTTPException(400, f"config.json 에 {exc} 가 없습니다(언어 모델이 아니거나 형식이 다름)") from exc
    ms = inspect.load(_data())
    ms[m["key"]] = m
    inspect.save(_data(), ms)
    return m


@router.delete("/models/{key:path}")
def delete(key: str) -> dict:
    ms = inspect.load(_data())
    if ms.pop(key, None) is None:
        raise HTTPException(404, "없는 모델")
    inspect.save(_data(), ms)
    return {"deleted": key}


@router.get("/graph")
def get_graph() -> dict:
    return graph.build(inspect.load(_data()))


@router.get("/compare")
def compare(a: str, b: str) -> dict:
    ms = inspect.load(_data())
    if a not in ms or b not in ms:
        raise HTTPException(404, "읽은 모델이 아닙니다")
    return {"a": a, "b": b, "changes": graph.compare(ms[a], ms[b])}
