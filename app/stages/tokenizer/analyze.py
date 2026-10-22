"""TK1~TK6 토크나이저 · 표현 공간: 같은 글을 여러 모델의 토크나이저로 나눠 토큰 효율 · 쪼개지는 모양 · 어휘 · 정규화 영향 · 위치 표현 ·
이미지 한 장의 토큰 비용을 잰다.

토큰 수는 맥락 · 비용 · 지연을 모두 곱하는 계수다. 같은 '맥락 32K' 도 한국어 글자당 토큰이 1.5배인 모델에는 실제로 넣을 수 있는 글이
2/3 이다. 그래서 같은 글 종류(일반 한국어 · 법령 · AS 매뉴얼 · 코드 · 영어)를 모델마다 나눠 글자당 토큰을 비교하고, 압축 보호(KC1) ·
검색 규칙이 기대는 표시('WM-200' · '제3조의2' · 'E4')가 몇 토큰으로 어떻게 쪼개지는지 본다. 토크나이저 파일만 받는다(가중치 없음).
"""

import json
import unicodedata
from pathlib import Path
from typing import Any

SAMPLES: dict[str, str] = {
    "한국어 일반": "고객님, 불편을 드려 죄송합니다. 세탁기 문이 열리지 않을 때는 먼저 전원을 끄고 잠시 기다린 뒤 다시 열어 보세요. 그래도 열리지 않으면 상담원에게 연결해 드리겠습니다.",
    "법령": "제43조(임금 지급) ① 임금은 통화로 직접 근로자에게 그 전액을 지급하여야 한다. ② 임금은 매월 1회 이상 일정한 날짜를 정하여 지급하여야 한다. 제43조의2(체불사업주 명단 공개)",
    "AS 매뉴얼": "WM-200 표시창에 E4 가 뜨면 배수 오류입니다. 배수 필터(지름 45mm)를 시계 반대 방향으로 돌려 꺼내고 30분 뒤 '헹굼+탈수'를 실행하세요. DR-300 의 d80 은 배기 막힘입니다.",
    "코드": 'def answer_once(db, question, cfg):\n    results = run_search(db, question, cfg)\n    if not results:\n        return {"answer": NOT_FOUND}\n    return llm.chat(cfg, SYSTEM, prompt(question, results))\n',
    "영어": "If the washing machine door does not open, turn off the power, wait a moment, and try again. If it still does not open, we will connect you to an agent.",
}
MARKS = ["WM-200", "E4", "d80", "제3조의2", "제43조", "2026년 10월 22일", "010-1234-5678", "30분"]


def load(hf_id: str) -> Any:
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(hf_id)


def _n(tok: Any, text: str) -> int:
    return len(tok(text, add_special_tokens=False)["input_ids"])


def pieces(tok: Any, text: str) -> list[str]:
    ids = tok(text, add_special_tokens=False)["input_ids"]
    return [tok.decode([i]) for i in ids]


def efficiency(tok: Any, samples: dict[str, str] | None = None) -> dict[str, Any]:
    """글 종류마다 토큰 수 · 글자당 토큰 · 1,000자당 토큰."""
    out = {}
    for k, t in (samples or SAMPLES).items():
        n = _n(tok, t)
        out[k] = {"chars": len(t), "tokens": n, "tokens_per_char": round(n / len(t), 3), "per_1000_chars": round(n / len(t) * 1000)}
    return out


def marks(tok: Any) -> list[dict[str, Any]]:
    """표시가 쪼개지는 모양 — 바이트 조각(�)으로 나뉘면 글자 경계가 토큰 경계와 다르다는 뜻(압축 · 자르기에서 조심)."""
    out = []
    for m in MARKS:
        ps = pieces(tok, m)
        out.append({"mark": m, "tokens": len(ps), "pieces": ps, "byte_split": any("�" in p for p in ps)})
    return out


def vocab(tok: Any) -> dict[str, Any]:
    """어휘 크기 · 한글이 든 조각의 몫 · 한글 완성형 한 글자 조각 수 · 특수 토큰."""
    v = tok.get_vocab()
    hangul = single = 0
    for t in v:
        s = tok.convert_tokens_to_string([t]) if hasattr(tok, "convert_tokens_to_string") else t
        if any("가" <= ch <= "힣" for ch in s):
            hangul += 1
            if len(s.strip()) == 1:
                single += 1
    return {"size": len(v), "hangul_pieces": hangul, "hangul_share": round(hangul / max(1, len(v)), 4), "hangul_single_syllables": single,
            "special": sorted(str(x) for x in (tok.all_special_tokens or []))[:20]}  # fmt: skip


def normalization(tok: Any) -> dict[str, Any]:
    """같은 글의 정규화 형태(NFC · NFD · 전각 숫자 · 보이지 않는 문자)에 따른 토큰 수 — 다르면 캐시 · 검색 · 보호 규칙이 빗나간다."""
    base = SAMPLES["AS 매뉴얼"]
    full = base.translate(str.maketrans("0123456789", "０１２３４５６７８９"))
    zw = base.replace(" ", " ​")
    forms = {
        "NFC(보통)": unicodedata.normalize("NFC", base),
        "NFD(자모 분리)": unicodedata.normalize("NFD", base),
        "전각 숫자": full,
        "보이지 않는 문자": zw,
    }
    n0 = _n(tok, forms["NFC(보통)"])
    return {k: {"tokens": _n(tok, t), "vs_nfc": round(_n(tok, t) / n0, 2)} for k, t in forms.items()}


def config_costs(hf_id: str) -> dict[str, Any]:
    """설정에서: 어휘 × 은닉(임베딩 · 출력층 크기, 같이 쓰나) · 위치 표현(rope θ · 확장) · 이미지 한 장의 토큰(패치 · 병합)."""
    from huggingface_hub import hf_hub_download

    try:
        cfg = json.loads(Path(hf_hub_download(hf_id, "config.json")).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — 설정이 없거나 승인이 필요한 저장소
        return {"error": f"{type(exc).__name__}"}
    c = cfg.get("text_config") or cfg
    vsz, h = int(c.get("vocab_size") or 0), int(c.get("hidden_size") or 0)
    tied = bool(c.get("tie_word_embeddings", cfg.get("tie_word_embeddings", False)))
    rope = {"theta": c.get("rope_theta") or (c.get("rope_parameters") or {}).get("rope_theta"), "scaling": c.get("rope_scaling"),
            "max_positions": c.get("max_position_embeddings")}  # fmt: skip
    img = None
    vc = cfg.get("vision_config")
    if vc:
        size, patch = vc.get("image_size"), vc.get("patch_size")
        merge = vc.get("spatial_merge_size") or 1
        if size and patch:
            img = (int(size) // int(patch)) ** 2 // (int(merge) ** 2)
        mm = cfg.get("mm_tokens_per_image") or cfg.get("vision_soft_tokens_per_image")
        img = int(mm) if mm else img
    emb = vsz * h
    return {"vocab_size": vsz, "hidden": h, "tied": tied, "embedding_params_m": round(emb / 1e6, 1), "head_params_m": 0 if tied else round(emb / 1e6, 1),
            "rope": rope, "image_tokens": img}  # fmt: skip


def compare(hf_ids: list[str], progress=lambda f, m: None) -> dict[str, Any]:
    rows = []
    for i, hid in enumerate(hf_ids):
        progress(i / max(1, len(hf_ids)), hid)
        try:
            tok = load(hid)
        except Exception as exc:  # noqa: BLE001 — 없는 저장소 · 승인 필요 · 오프라인
            rows.append({"hf_id": hid, "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
            continue
        rows.append({"hf_id": hid, "efficiency": efficiency(tok), "marks": marks(tok), "vocab": vocab(tok), "normalization": normalization(tok),
                     "config": config_costs(hid)})  # fmt: skip
    ok = [r for r in rows if "efficiency" in r]
    if ok:
        for k in SAMPLES:
            best = min(r["efficiency"][k]["tokens"] for r in ok)
            for r in ok:
                r["efficiency"][k]["vs_best"] = round(r["efficiency"][k]["tokens"] / best, 2)
    return {"models": rows, "samples": SAMPLES}
