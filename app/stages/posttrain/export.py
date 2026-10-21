"""P7 배포 형식 변환: 병합한 모델(HF 폴더) → GGUF(llama.cpp 의 convert_hf_to_gguf.py) → 양자화(llama-quantize) → llama-server.

변환 스크립트는 llama.cpp 저장소에 있고 실행 파일 묶음에는 없다 — LLAMA_CONVERT_SCRIPT 가 있으면 앱이 돌리고, 없으면 실행할 명령을
그대로 보여 준다(무엇을 해야 하는지 알게). 양자화는 llama-server 와 같은 폴더의 llama-quantize. 변환 뒤에는 서빙 실측(S5)이나
LLM 비교(7b)로 '학습 효과가 양자화 뒤에도 남았나'를 같은 질문으로 다시 잰다.
"""

import subprocess
import sys
from pathlib import Path
from typing import Any

from app.core.config import get_settings


def plan(model_dir: Path, name: str, quant: str = "Q4_0") -> dict[str, Any]:
    st = get_settings()
    out_dir = Path(st.llm_models_dir) if st.llm_models_dir else model_dir.parent
    f16 = out_dir / f"{name}-f16.gguf"
    qf = out_dir / f"{name}-{quant}.gguf"
    quantize = (
        Path(st.llama_server_bin).with_name("llama-quantize.exe" if sys.platform == "win32" else "llama-quantize")
        if st.llama_server_bin
        else None
    )
    script = Path(st.llama_convert_script) if st.llama_convert_script else None
    return {"f16": f16, "quantized": qf, "quantize_bin": quantize, "script": script,
            "commands": [f'python "{script or "llama.cpp/convert_hf_to_gguf.py"}" "{model_dir}" --outfile "{f16}" --outtype f16',
                         f'"{quantize or "llama-quantize"}" "{f16}" "{qf}" {quant}']}  # fmt: skip


def run(model_dir: Path, name: str, quant: str = "Q4_0", progress: Any = None) -> dict[str, Any]:
    p = plan(model_dir, name, quant)
    steps = []
    if not p["script"] or not p["script"].exists():
        return {"ok": False, "reason": "LLAMA_CONVERT_SCRIPT 가 없어 변환 명령만 보여 줍니다", "commands": p["commands"]}
    if progress:
        progress(0.1, "GGUF 로 변환(f16)")
    r = subprocess.run([sys.executable, str(p["script"]), str(model_dir), "--outfile", str(p["f16"]), "--outtype", "f16"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=3600)  # fmt: skip
    steps.append({"step": "convert", "code": r.returncode, "tail": (r.stdout + r.stderr)[-1500:]})
    if r.returncode != 0:
        return {
            "ok": False,
            "reason": "변환 실패(변환 스크립트는 gguf 패키지가 필요 — uv add gguf)",
            "steps": steps,
            "commands": p["commands"],
        }
    if p["quantize_bin"] and p["quantize_bin"].exists():
        if progress:
            progress(0.6, f"{quant} 로 양자화")
        q = subprocess.run([str(p["quantize_bin"]), str(p["f16"]), str(p["quantized"]), quant], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=3600)  # fmt: skip
        steps.append({"step": "quantize", "code": q.returncode, "tail": (q.stdout + q.stderr)[-1500:]})
    files = [{"path": str(f), "gb": round(f.stat().st_size / 2**30, 2)} for f in (p["f16"], p["quantized"]) if f.exists()]
    return {"ok": bool(files), "files": files, "steps": steps, "commands": p["commands"]}
