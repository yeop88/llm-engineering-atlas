"""IP4 희소 특징(SAE): 한 층의 토큰 은닉 상태를 수천 개의 희소한 특징으로 다시 표현하고, 특징마다 가장 세게 켜지는 글 조각으로 뜻을 붙인다.

은닉 상태의 차원 하나는 여러 뜻이 섞여 있다(중첩). 희소 오토인코더는 h ≈ W_dec · relu(W_enc · h + b) 를 L1 로 희소하게 배워, 특징 하나가
'법 조문 번호' · '거절 말투' 같은 한 개념에 가깝게 한다. 이 PC(CPU)에서 돌도록 작게: 토큰 수만 · 특징 수 배수 4~8 · 몇 백 걸음.
재구성 오차(설명한 분산) · 평균 켜진 특징 수(L0) · 한 번도 안 켜진 특징 비율을 함께 본다 — 희소할수록 해석은 쉽지만 재구성이 나빠진다.
"""

from typing import Any

import numpy as np
import torch


@torch.no_grad()
def token_states(
    model: Any, tok: Any, texts: list[str], layer: int, max_tokens: int = 128
) -> tuple[torch.Tensor, list[tuple[int, int]], list[list[str]]]:
    """→ (토큰 은닉 상태 (N, d), 토큰마다 (글 번호, 위치), 글마다 토큰 글자)."""
    hs, where, toks = [], [], []
    for ti, t in enumerate(texts):
        ids = tok(t, add_special_tokens=False)["input_ids"][:max_tokens]
        if not ids:
            toks.append([])
            continue
        out = model(torch.tensor([ids], device=model.device), output_hidden_states=True)
        h = out.hidden_states[layer][0].float().cpu()
        hs.append(h)
        where += [(ti, j) for j in range(len(ids))]
        toks.append([tok.decode([i]) for i in ids])
    return torch.cat(hs) if hs else torch.zeros(0, 1), where, toks


def train(
    x: torch.Tensor, mult: int = 4, l1: float = 1e-3, steps: int = 400, lr: float = 1e-3, batch: int = 256, seed: int = 7
) -> dict[str, Any]:
    torch.manual_seed(seed)
    mu, sd = x.mean(0), x.std(0) + 1e-6
    z = (x - mu) / sd  # 차원마다 크기가 달라 L1 이 큰 차원만 보지 않게
    d, m = z.shape[1], z.shape[1] * mult
    enc = torch.nn.Linear(d, m)
    dec = torch.nn.Linear(m, d, bias=False)
    opt = torch.optim.Adam(list(enc.parameters()) + list(dec.parameters()), lr=lr)
    log = []
    for s in range(steps):
        b = z[torch.randint(0, len(z), (min(batch, len(z)),))]
        f = torch.relu(enc(b))
        rec = dec(f)
        loss = ((rec - b) ** 2).mean() + l1 * f.abs().sum(1).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
        with torch.no_grad():
            dec.weight /= dec.weight.norm(dim=0, keepdim=True) + 1e-8  # 특징 방향 길이를 1 로 — L1 을 피해 방향만 키우는 꼼수를 막는다
        if s % 50 == 0 or s == steps - 1:
            log.append({"step": s, "loss": round(loss.item(), 4)})
    with torch.no_grad():
        f = torch.relu(enc(z))
        rec = dec(f)
        ev = 1 - float(((rec - z) ** 2).sum() / ((z - z.mean(0)) ** 2).sum())
        l0 = float((f > 0).float().sum(1).mean())
        dead = float(((f > 0).sum(0) == 0).float().mean())
    return {
        "enc": enc,
        "dec": dec,
        "mu": mu,
        "sd": sd,
        "features": f,
        "explained": round(ev, 4),
        "l0": round(l0, 1),
        "dead": round(dead, 4),
        "n_features": m,
        "log": log,
    }


def top_features(
    res: dict[str, Any], where: list[tuple[int, int]], toks: list[list[str]], k: int = 12, n_ex: int = 5, window: int = 6
) -> list[dict[str, Any]]:
    """자주 · 세게 켜지는 특징 k 개와 가장 세게 켜진 글 조각(앞뒤 window 토큰, 켜진 토큰을 ⟦ ⟧ 로)."""
    f = res["features"].numpy()
    freq = (f > 0).mean(0)
    strength = f.max(0)
    cand = [j for j in np.argsort(-(freq * strength)) if 0.001 < freq[j] < 0.5][:k]  # 거의 늘 켜지는 특징은 뜻을 읽기 어렵다
    out = []
    for j in cand:
        top = np.argsort(-f[:, j])[:n_ex]
        ex = []
        for r in top:
            ti, pos = where[r]
            t = toks[ti]
            a, b = max(0, pos - window), min(len(t), pos + window + 1)
            ex.append("".join(t[a:pos]) + "⟦" + t[pos] + "⟧" + "".join(t[pos + 1 : b]))
        out.append({"feature": int(j), "freq": round(float(freq[j]), 4), "max": round(float(strength[j]), 3), "examples": ex})
    return out
