"""BM4 페이지 KV 캐시: KV 를 작은 블록으로 나눠 필요할 때 붙이고, 같은 앞부분(시스템 프롬프트 · 근거)은 블록을 나눠 쓴다.

요청마다 최대 길이만큼 KV 를 미리 잡으면, 실제로는 메모리가 남는데도 새 요청을 받지 못한다(예약했지만 안 쓴 칸 = 내부 낭비).
설계는 페이지 어텐션(PagedAttention — vLLM 등이 쓰는 기법, 이름만 참고)의 '논리 블록 → 물리 블록 표' 를 따라 새로 작성했다:
- 블록 = 토큰 block_size 개의 K · V. 요청은 블록 번호 목록(블록 표)만 가진다 — 연속된 메모리가 필요 없어 조각이 생기지 않는다.
- 앞부분 공유: 가득 찬 블록은 '앞 블록 해시 + 이 블록 토큰' 으로 해시해 같은 내용이면 같은 물리 블록을 참조 수만 늘려 쓴다.
  마지막(덜 찬) 블록은 요청마다 따로 — 이어 쓰면 내용이 달라지기 때문(쓰기 시 복사 대신 '찬 블록만 공유' 로 단순하게).
- 반납: 요청이 끝나면 참조 수를 줄이고 0 이 된 블록을 빈 목록으로. 공유 블록은 다른 요청이 쓰는 동안 남는다.
같은 메모리(블록 수)에 요청 기록을 넣어 '미리 잡기' 와 '페이지' 의 동시 요청 수 · 낭비 · 공유로 아낀 블록을 비교한다(simulate).
"""

import hashlib
import random
from typing import Any


class PagedKV:
    def __init__(self, num_blocks: int, block_size: int = 16, share_prefix: bool = True):
        self.bs, self.share = block_size, share_prefix
        self.free = list(range(num_blocks))[::-1]
        self.ref = [0] * num_blocks
        self.by_hash: dict[str, int] = {}
        self.hash_of: dict[int, str] = {}
        self.tables: dict[str, list[int]] = {}
        self.lengths: dict[str, int] = {}
        self.tokens: dict[str, list[int]] = {}
        self.shared_hits = 0

    def _alloc(self) -> int | None:
        return self.free.pop() if self.free else None

    def _release(self, b: int) -> None:
        self.ref[b] -= 1
        if self.ref[b] == 0:
            h = self.hash_of.pop(b, None)
            if h is not None and self.by_hash.get(h) == b:
                del self.by_hash[h]
            self.free.append(b)

    def can_fit(self, n_tokens: int) -> bool:
        return len(self.free) >= -(-n_tokens // self.bs)

    def add(self, rid: str, prompt: list[int]) -> bool:
        """프롬프트를 넣는다(앞부분 공유). 블록이 모자라면 아무것도 잡지 않고 False."""
        table: list[int] = []
        h = ""
        n_full = len(prompt) // self.bs
        need_new = 0
        plan: list[tuple[str, int | None]] = []
        for i in range(-(-len(prompt) // self.bs)):
            chunk = prompt[i * self.bs : (i + 1) * self.bs]
            if i < n_full and self.share:
                h = hashlib.blake2b((h + "|" + ",".join(map(str, chunk))).encode(), digest_size=12).hexdigest()
                hit = self.by_hash.get(h)
                plan.append((h, hit))
                need_new += hit is None
            else:
                plan.append(("", None))
                need_new += 1
        if need_new > len(self.free):
            return False
        for h, hit in plan:
            if hit is not None:
                self.ref[hit] += 1
                self.shared_hits += 1
                table.append(hit)
                continue
            b = self._alloc()
            assert b is not None
            self.ref[b] = 1
            if h:
                self.by_hash[h], self.hash_of[b] = b, h
            table.append(b)
        self.tables[rid], self.lengths[rid], self.tokens[rid] = table, len(prompt), list(prompt)
        return True

    def append(self, rid: str, token: int) -> bool:
        """생성 토큰 하나. 마지막 블록이 차면 새 블록 — 없으면 False(선점 · 대기 대상)."""
        n = self.lengths[rid]
        if n % self.bs == 0:
            b = self._alloc()
            if b is None:
                return False
            self.ref[b] = 1
            self.tables[rid].append(b)
        self.lengths[rid] = n + 1
        self.tokens[rid].append(token)
        return True

    def finish(self, rid: str) -> None:
        for b in self.tables.pop(rid, []):
            self._release(b)
        self.lengths.pop(rid, None)
        self.tokens.pop(rid, None)

    def used_blocks(self) -> int:
        return sum(1 for r in self.ref if r > 0)

    def logical_blocks(self) -> int:
        return sum(len(t) for t in self.tables.values())


def requests(n: int = 200, prefix_tokens: int = 600, prefixes: int = 3, prompt_mean: int = 300, out_mean: int = 200, seed: int = 0,
             from_traces: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """요청 기록: 같은 시스템 프롬프트(앞부분 prefix_tokens, prefixes 종) + 질문 · 근거(prompt_mean) + 답 길이(out_mean).
    요청 기록(tokens_in · tokens_out)을 주면 질문 · 답 길이를 거기서 쓴다."""
    rnd = random.Random(seed)
    heads = [[rnd.randrange(1000, 50000) for _ in range(prefix_tokens)] for _ in range(prefixes)]
    out = []
    for i in range(n):
        if from_traces:
            t = from_traces[i % len(from_traces)]
            p_len, o_len = max(1, int(t.get("tokens_in") or prompt_mean)), max(1, int(t.get("tokens_out") or out_mean))
        else:
            p_len, o_len = max(8, int(rnd.expovariate(1 / prompt_mean))), max(4, int(rnd.expovariate(1 / out_mean)))
        head = heads[rnd.randrange(prefixes)] if prefixes else []
        body = [rnd.randrange(1000, 50000) for _ in range(p_len)]  # 질문 · 근거(요청마다 다름) — 앞부분(시스템 프롬프트) 뒤에 붙는다
        out.append({"id": f"r{i}", "prompt": head + body, "out": o_len})
    return out


def simulate(reqs: list[dict[str, Any]], num_blocks: int, block_size: int = 16, max_len: int = 4096, mode: str = "paged") -> dict[str, Any]:
    """같은 블록 수로 요청을 차례로 받아 토큰 단위로 진행한다. mode: reserve(최대 길이 미리 잡기) · paged · paged_share.
    → 동시에 돈 요청 수(평균 · 최대) · 쓴 블록 중 실제 토큰이 찬 비율 · 공유로 아낀 블록 · 다 끝내는 데 든 걸음."""
    kv = PagedKV(num_blocks, block_size, share_prefix=(mode == "paged_share"))
    queue = list(reqs)
    active: dict[str, dict[str, Any]] = {}
    steps, conc, util, eff, saved = 0, [], [], [], []
    reserve_blocks = -(-max_len // block_size)
    reserved: dict[str, list[int]] = {}
    while queue or active:
        # 받기: 들어가는 한 앞에서부터(순서 유지 — 큰 요청이 계속 밀리지 않게 앞 요청이 안 들어가면 멈춤)
        while queue:
            r = queue[0]
            if mode == "reserve":
                if len(kv.free) < reserve_blocks:
                    break
                reserved[r["id"]] = [kv.free.pop() for _ in range(reserve_blocks)]
                for b in reserved[r["id"]]:
                    kv.ref[b] = 1
                kv.lengths[r["id"]] = len(r["prompt"])
            elif not kv.add(r["id"], r["prompt"]):
                break
            active[r["id"]] = {"left": min(r["out"], max_len - len(r["prompt"])) if mode == "reserve" else r["out"]}
            queue.pop(0)
        if not active:
            # 요청 하나도 못 받음 = 이 메모리로는 이 요청이 안 들어간다(그 요청은 버리고 기록)
            queue.pop(0)
            continue
        steps += 1
        conc.append(len(active))
        done = []
        for rid, a in active.items():
            if a["left"] <= 0:
                done.append(rid)
                continue
            if mode == "reserve":
                kv.lengths[rid] += 1
                a["left"] -= 1
            elif kv.append(rid, 0):
                a["left"] -= 1
            else:
                # 블록이 없어 이번 걸음은 못 감 — 실제 서버는 선점(나중 요청을 빼서 다시 계산)한다. 여기선 기다림으로 센다
                a["stalled"] = a.get("stalled", 0) + 1
                if a["stalled"] > 50:  # 서로 기다려 멈춤 — 가장 늦게 들어온 요청을 끝낸 것으로(선점과 같은 효과의 단순화)
                    done.append(rid)
        for rid in done:
            if mode == "reserve":
                for b in reserved.pop(rid):
                    kv._release(b)
                kv.lengths.pop(rid, None)
            else:
                kv.finish(rid)
            active.pop(rid)
        used = kv.used_blocks() if mode != "reserve" else len(active) * reserve_blocks
        logical = kv.logical_blocks() if mode != "reserve" else used
        filled = sum(kv.lengths.get(r, 0) for r in active)
        util.append(filled / max(1, logical * block_size))  # 잡은 칸 중 실제 토큰이 든 비율(내부 낭비의 반대)
        eff.append(filled / max(1, used * block_size))  # 물리 칸 하나가 담는 토큰 — 공유하면 1 을 넘는다
        if mode == "paged_share":
            saved.append(kv.logical_blocks() - kv.used_blocks())
    n = len(conc)
    return {"mode": mode, "steps": steps, "mean_concurrency": round(sum(conc) / n, 2) if n else 0, "max_concurrency": max(conc, default=0),
            "token_fill": round(sum(util) / len(util), 3) if util else 0, "tokens_per_slot": round(sum(eff) / len(eff), 3) if eff else 0,
            "shared_blocks_saved": round(sum(saved) / len(saved), 1) if saved else 0,
            "shared_hits": kv.shared_hits}  # fmt: skip


def compare(
    reqs: list[dict[str, Any]], kv_bytes_per_token: int, budget_gb: float, block_size: int = 16, max_len: int = 4096
) -> dict[str, Any]:
    """KV 메모리 예산(GB)을 블록 수로 바꿔 세 방식을 같은 요청으로."""
    blocks = int(budget_gb * 2**30 // max(1, kv_bytes_per_token * block_size))
    res = [simulate(reqs, blocks, block_size, max_len, m) for m in ("reserve", "paged", "paged_share")]
    return {"blocks": blocks, "block_size": block_size, "max_len": max_len, "budget_gb": budget_gb, "kv_bytes_per_token": kv_bytes_per_token,
            "results": res}  # fmt: skip
