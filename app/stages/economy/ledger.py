"""EC5 · EC7 흉내 장부: 복식 기입(모든 거래는 한 계정에서 빠지고 다른 계정에 더해짐) · 에스크로 묶기 · 풀기 · 돌려주기 · 해시 사슬 영수증.

실제 결제는 하지 않는다(맵 원칙). 대신 돈이 움직이는 규칙을 그대로 지키는 장부를 두고 규칙을 시험한다.
- 계정: 지갑(맡긴 사람) · 에스크로(묶인 돈) · 판매자마다 받는 계정. 모든 기입의 합은 0 이어야 한다(돈이 생기거나 사라지지 않음).
- 같은 거래를 두 번 처리하지 않게 거래 id 를 열쇠로 둔다(재시도 · 중복 요청에도 한 번만 — 이중 지불 방지).
- 기입마다 앞 기입의 해시를 넣어 사슬로 잇는다. 나중에 한 줄을 고치면 그 뒤 해시가 모두 어긋나 감사에서 드러난다(요청 기록의 해시 사슬과 같은 생각).
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Ledger:
    balances: dict[str, int] = field(default_factory=dict)  # 원 단위 정수 — 부동소수 반올림으로 돈이 새지 않게
    entries: list[dict[str, Any]] = field(default_factory=list)
    done: set[str] = field(default_factory=set)
    escrow: dict[str, dict[str, Any]] = field(default_factory=dict)

    def _post(self, tx: str, kind: str, src: str, dst: str, amount: int, memo: str = "") -> dict[str, Any]:
        if amount <= 0:
            raise ValueError("금액은 양수")
        if self.balances.get(src, 0) < amount and not src.startswith("world"):
            raise ValueError(f"{src} 잔액 부족")
        self.balances[src] = self.balances.get(src, 0) - amount
        self.balances[dst] = self.balances.get(dst, 0) + amount
        prev = self.entries[-1]["hash"] if self.entries else "0" * 16
        e = {"n": len(self.entries) + 1, "tx": tx, "kind": kind, "from": src, "to": dst, "amount": amount, "memo": memo, "prev": prev}
        e["hash"] = hashlib.sha256(json.dumps(e, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        self.entries.append(e)
        return e

    def fund(self, account: str, amount: int) -> None:
        self._post(f"fund-{len(self.entries)}", "fund", "world", account, amount, "충전")

    def hold(self, tx: str, payer: str, payee: str, amount: int) -> dict[str, Any]:
        """에스크로에 묶기 — 결과를 확인하기 전까지 판매자에게 가지 않는다. 같은 tx 는 한 번만."""
        if f"hold:{tx}" in self.done:
            return {"duplicate": True, "tx": tx}
        e = self._post(tx, "hold", payer, f"escrow:{tx}", amount, f"→ {payee}")
        self.escrow[tx] = {"payer": payer, "payee": payee, "amount": amount, "state": "held"}
        self.done.add(f"hold:{tx}")
        return e

    def release(self, tx: str) -> dict[str, Any]:
        es = self.escrow.get(tx)
        if not es or es["state"] != "held":
            return {"skipped": True, "tx": tx, "state": es and es["state"]}
        e = self._post(tx, "release", f"escrow:{tx}", f"merchant:{es['payee']}", es["amount"], "검증 통과 · 정산")
        es["state"] = "released"
        return e

    def refund(self, tx: str, amount: int | None = None, reason: str = "") -> dict[str, Any]:
        es = self.escrow.get(tx)
        if not es or es["state"] != "held":
            return {"skipped": True, "tx": tx, "state": es and es["state"]}
        amt = es["amount"] if amount is None else min(amount, es["amount"])
        e = self._post(tx, "refund", f"escrow:{tx}", es["payer"], amt, reason)
        if amt < es["amount"]:  # 부분 환불 — 나머지는 판매자에게(일부만 이행한 경우)
            self._post(tx, "release", f"escrow:{tx}", f"merchant:{es['payee']}", es["amount"] - amt, "부분 정산")
        es["state"] = "refunded" if amt == es["amount"] else "partial"
        return e

    def audit(self) -> dict[str, Any]:
        """합이 0 인가(충전한 만큼만 있나) · 해시 사슬이 이어지나 · 에스크로에 남은 돈."""
        funded = sum(e["amount"] for e in self.entries if e["kind"] == "fund")
        held = sum(v for k, v in self.balances.items() if not k.startswith("world"))
        chain_ok, prev = True, "0" * 16
        for e in self.entries:
            body = {k: v for k, v in e.items() if k != "hash"}
            if (
                e["prev"] != prev
                or hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16] != e["hash"]
            ):
                chain_ok = False
                break
            prev = e["hash"]
        return {"balanced": held == funded, "chain_ok": chain_ok, "in_escrow": sum(v for k, v in self.balances.items() if k.startswith("escrow:")),
                "entries": len(self.entries)}  # fmt: skip
