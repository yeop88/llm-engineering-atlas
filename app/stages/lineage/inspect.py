"""LN1~LN6 모델 하나 읽기: GGUF 머리말 · HF config.json · 모델 카드 → 계열 · 세대 · 구조 숫자 · 맥락 · 모달리티 · 라이선스 · 기반 모델.

모델 이름보다 설정 파일이 정확하다. GGUF 는 머리말에 기반 모델 저장소(general.base_model.*) · 제작사 · 양자화한 곳 · 크기 표시 · 라이선스를,
HF 는 config.json 에 층 · 차원 · 전문가 · 맥락 · 위치 확장을, 모델 카드 메타에 라이선스 · 기반 모델 태그를 둔다. 여기서 사실만 뽑고
추측은 표시한다(계열 · 세대는 이름 규칙으로 추정 — `guessed`). 라이선스는 id 와 링크가 서로 다른 라이선스를 가리키면 '확인 필요'
(예: id 는 apache-2.0 인데 링크가 그 회사의 전용 라이선스) — 배포 직전에 알면 비용이 크다.
"""

import json
import re
from pathlib import Path
from typing import Any

from app.stages.bigmodel import gguf, plan

# 이름 → (계열, 제작사). 순서대로 처음 맞는 것 — 계열이 같으면 토크나이저 · 채팅 틀 · 약점이 비슷하다
FAMILIES = [
    (re.compile(r"qwen", re.I), "Qwen", "Alibaba Qwen"), (re.compile(r"gemma", re.I), "Gemma", "Google"),
    (re.compile(r"llama", re.I), "Llama", "Meta"), (re.compile(r"exaone", re.I), "EXAONE", "LG AI Research"),
    (re.compile(r"kanana", re.I), "Kanana", "Kakao"), (re.compile(r"mistral|mixtral|ministral", re.I), "Mistral", "Mistral AI"),
    (re.compile(r"\bphi[-\d]", re.I), "Phi", "Microsoft"), (re.compile(r"deepseek", re.I), "DeepSeek", "DeepSeek"),
    (re.compile(r"hyperclova|hcx", re.I), "HyperCLOVA X", "NAVER"),
    # SKT A.X — 이름에 점이 들어가 'ax' 로는 잡히지 않는다(실측에서 '기타' 로 나옴)
    (re.compile(r"A\.X|skt/a\.x", re.I), "A.X", "SKT"), (re.compile(r"gpt-oss", re.I), "gpt-oss", "OpenAI"),
]  # fmt: skip
GEN = re.compile(r"(?:qwen|gemma|llama|exaone|kanana|phi|deepseek|mistral|a\.x)[-_ ]?v?(\d+(?:\.\d+)?)", re.I)
LICENSE_HINT = [
    ("gemma", "Gemma 라이선스"),
    ("llama", "Llama 커뮤니티 라이선스"),
    ("kanana", "Kanana 라이선스"),
    ("exaone", "EXAONE 라이선스"),
]


def family(name: str) -> tuple[str, str, bool]:
    for rx, fam, org in FAMILIES:
        if rx.search(name or ""):
            return fam, org, True
    return "기타", "", True


def generation(name: str) -> str | None:
    m = GEN.search(name or "")
    return m.group(1) if m else None


def license_check(lic: str | None, link: str | None, name: str | None = None) -> dict[str, Any]:
    """id · 링크 · 이름이 서로 다른 라이선스를 가리키면 확인 필요."""
    lic, link, name = (lic or "").lower(), (link or "").lower(), (name or "").lower()
    notes = []
    for key, label in LICENSE_HINT:
        if key in link and key not in lic and key not in name:
            notes.append(f"id 는 '{lic or '없음'}' 인데 링크는 {label}")
    if lic in ("other", "") and not name:
        notes.append("라이선스 이름이 없음")
    return {"id": lic or None, "name": name or None, "link": link or None, "check": bool(notes), "notes": notes}


def from_gguf(path: str | Path) -> dict[str, Any]:
    g = gguf.read(path)
    m, a = g["meta"], gguf.arch(g["meta"])
    p = plan.from_gguf(path)
    base = [{"name": m.get(f"general.base_model.{i}.name"), "org": m.get(f"general.base_model.{i}.organization"), "repo": m.get(f"general.base_model.{i}.repo_url")}
            for i in range(int(m.get("general.base_model.count") or 0))]  # fmt: skip
    nm = m.get("general.basename") or (base[0]["name"] if base else "") or Path(path).stem
    # 계열은 모델 · 파일 이름이 먼저 — 구조 이름(general.architecture)은 빌려 쓴 구조일 수 있다(kanana-2 는 qwen3 구조)
    fam, org, _ = family(f"{nm} {Path(path).name}")
    if fam == "기타":
        fam, org, _ = family(a["arch"])
    folder = Path(path).parent
    stem = Path(path).name.lower().split("_")[0].split("-it")[0]
    mmproj = any("mmproj" in f.name.lower() and stem.split(".")[0][:10] in f.name.lower() for f in folder.glob("*.gguf"))
    tags = m.get("general.tags") or []
    tags = tags if isinstance(tags, list) else []
    mods = ["text"] + (["image"] if mmproj or any("image" in str(t) or "any-to-any" in str(t) for t in tags) else [])
    ctx_train = a.get("context")
    rope = {k.split(".", 1)[1]: m[k] for k in m if k.startswith(f"{a['arch']}.rope.scaling.")}
    return {"key": f"gguf:{Path(path).name}", "source": "gguf", "file": Path(path).name, "name": nm, "family": fam, "org": org or (base[0]["org"] if base else ""),
            "generation": generation(nm) or generation(a["arch"]), "guessed": ["family", "generation"], "arch": a["arch"], "size_label": m.get("general.size_label"),
            "params_b": p["params_b"], "experts": a.get("experts"), "experts_used": a.get("experts_used"), "layers": a.get("layers"), "hidden": a.get("hidden"),
            "kv_heads": a.get("kv_heads"), "context": {"trained": ctx_train, "rope_scaling": rope or None, "sliding_window": a.get("sliding_window")},
            "modalities": mods, "mmproj": mmproj, "license": license_check(m.get("general.license"), m.get("general.license.link"), m.get("general.license.name")),
            "base_models": base, "quantized_by": m.get("general.quantized_by"), "file_type": a.get("file_type"),
            "bpw": round(p["weights_bytes"] * 8 / max(1, p["params_b"] * 1e9), 2)}  # fmt: skip


def from_hf(hf_id: str, config: dict[str, Any], card: dict[str, Any] | None = None) -> dict[str, Any]:
    """HF config.json(+ 모델 카드 메타) → 같은 모양. 파라미터 수는 구조 × 1바이트 어림의 개수(bits 무관)."""
    c = config.get("text_config") or config
    p = plan.from_hf_config(config, "bf16")
    card = card or {}
    fam, org, _ = family(hf_id)
    vis = bool(config.get("vision_config") or "image" in str(card.get("pipeline_tag") or ""))
    audio = bool(config.get("audio_config"))
    base = card.get("base_model")
    base = base if isinstance(base, list) else ([base] if base else [])
    return {"key": f"hf:{hf_id}", "source": "hf", "file": None, "name": hf_id, "family": fam, "org": org or hf_id.split("/")[0], "generation": generation(hf_id),
            "guessed": ["family", "generation"], "arch": c.get("model_type"), "size_label": None, "params_b": p["params_b"],
            "experts": p["arch"].get("experts"), "experts_used": p["arch"].get("experts_used"), "layers": p["arch"].get("layers"), "hidden": p["arch"].get("hidden"),
            "kv_heads": p["arch"].get("kv_heads"), "context": {"trained": c.get("max_position_embeddings"), "rope_scaling": c.get("rope_scaling"),
            "sliding_window": c.get("sliding_window")}, "modalities": ["text"] + (["image"] if vis else []) + (["audio"] if audio else []), "mmproj": None,
            "license": license_check(card.get("license"), card.get("license_link"), card.get("license_name")),
            "base_models": [{"name": b, "org": b.split("/")[0], "repo": f"https://huggingface.co/{b}"} for b in base], "quantized_by": None,
            "file_type": None, "bpw": None}  # fmt: skip


def store_path(data_dir: Path) -> Path:
    p = data_dir / "lineage" / "models.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load(data_dir: Path) -> dict[str, dict[str, Any]]:
    p = store_path(data_dir)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def save(data_dir: Path, models: dict[str, dict[str, Any]]) -> None:
    store_path(data_dir).write_text(json.dumps(models, ensure_ascii=False, indent=1), encoding="utf-8")
