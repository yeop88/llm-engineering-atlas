"""VD1 영상 받기: 길이 · 크기 · fps · 소리 트랙을 확인하고, 일정 간격 프레임과 소리(16kHz)를 꺼낸다.

멀티모달 수집(MM)의 프레임 꺼내기는 '같은 장면이면 건너뛴다' — 색인할 프레임을 줄이려는 것이다. 추적은 같은 장면 안의 움직임을 봐야 하므로
여기서는 건너뛰지 않고 간격마다 다 꺼낸다(대신 길이 상한).
"""

import io
from typing import Any

import numpy as np
from PIL import Image

from app.stages.voice import audio

MAX_SIDE = 480


def decode(
    data: bytes, fps: float = 2.0, max_seconds: float = 600.0
) -> tuple[list[tuple[float, Image.Image]], np.ndarray | None, dict[str, Any]]:
    import av  # 무거워서 쓸 때만

    frames: list[tuple[float, Image.Image]] = []
    with av.open(io.BytesIO(data)) as c:
        if not c.streams.video:
            raise ValueError("영상 스트림이 없습니다")
        vs = c.streams.video[0]
        info = {"duration": round(float(c.duration / av.time_base), 2) if c.duration else None, "width": vs.codec_context.width,
                "height": vs.codec_context.height, "fps": float(vs.average_rate) if vs.average_rate else None, "audio": bool(c.streams.audio)}  # fmt: skip
        nxt = 0.0
        for fr in c.decode(vs):
            t = float(fr.time) if fr.time is not None else nxt
            if t + 1e-6 < nxt:
                continue
            if t > max_seconds:
                info["truncated"] = True
                break
            nxt = t + 1.0 / fps
            im = fr.to_image()
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            frames.append((round(t, 2), im))
    snd = None
    if info["audio"]:
        try:
            snd = audio.decode(data)[: int(max_seconds * audio.SR)]
        except Exception:  # noqa: BLE001 — 소리 코덱을 못 읽어도 영상 색인은 한다
            info["audio_error"] = True
    return frames, snd, info
