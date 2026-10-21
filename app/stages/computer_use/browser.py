"""CU1 화면 이해 · CU2 행동 실행 · CU3 상태 확인 — 흉내 브라우저(표준 라이브러리 HTML 파서).

화면 이해: HTML → 접근성 트리(역할 · 이름 · 값 · 요소 번호). 이름은 접근성 규칙대로 label[for] · 감싼 label · aria-label · 글자에서. 화면에 보이지
않는 요소(display:none · hidden · aria-hidden)는 트리에서 빼고 '숨은 글' 로 따로 모은다 — 사람이 볼 수 없는 글이 에이전트에게 지시로 들어가는
것이 웹 인젝션의 주된 길이다. 트리에서 빼되 감사(인젝션 탐지)에는 쓴다.

행동: click(번호) · type(번호, 글) · select(번호, 값) · check(번호) · navigate(주소) · back. 폼 안의 제출 버튼을 누르면 사이트의 submit 이 상태를 바꾼다.
상태 확인: 행동 전후의 주소 · 트리 지문 · 알림(role=alert) · 입력값을 비교해 '바뀐 것이 없음' · '오류 알림' 을 다음 걸음에 알린다.
브라우저 상태(사이트 상태 · 주소 · 입력값)는 dict 로 저장할 수 있다 — 승인 대기 뒤 이어 가기 · 재생용.
"""

import hashlib
import re
from html.parser import HTMLParser
from typing import Any

from app.stages.computer_use import sites

INTERACTIVE = {"a": "link", "button": "button", "select": "combobox", "textarea": "textbox"}


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.els: list[dict[str, Any]] = []
        self.stack: list[dict[str, Any]] = []
        self.hidden_depth = 0
        self.hidden_text: list[str] = []
        self.texts: list[str] = []
        self.labels: dict[str, str] = {}
        self.form: dict[str, Any] | None = None
        self.label_stack: list[dict[str, Any]] = []
        self.title = ""
        self._in_title = False
        self._open_el: dict[str, Any] | None = None
        self.n_forms = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        hidden = (
            "display:none" in a.get("style", "").replace(" ", "")
            or "hidden" in a
            or a.get("aria-hidden") == "true"
            or "hidden" in a.get("class", "").split()
        )
        if tag in ("p", "div", "span", "section", "td", "li", "label", "a", "button", "form", "table", "tr") and (
            hidden or self.hidden_depth
        ):
            self.hidden_depth += 1
            self.stack.append({"tag": tag, "hidden_marker": True})
            return
        self.stack.append({"tag": tag})
        if tag == "title":
            self._in_title = True
        if tag == "form":
            self.n_forms += 1
            self.form = {
                "action": a.get("action", ""),
                "id": self.n_forms,
            }  # 폼마다 번호 — 목록의 삭제 버튼처럼 폼이 여럿이면 입력값을 섞지 않게
        if tag == "label":
            self.label_stack.append({"for": a.get("for"), "text": ""})
        role = None
        if tag in INTERACTIVE:
            role = INTERACTIVE[tag]
        elif tag == "input":
            t = a.get("type", "text")
            role = {"checkbox": "checkbox", "radio": "radio", "submit": "button", "hidden": None}.get(t, "textbox")
        if role:
            el = {"eid": len(self.els) + 1, "role": role, "tag": tag, "name": a.get("aria-label", ""), "id": a.get("id", ""), "field": a.get("name", ""),
                  "value": a.get("value", ""), "type": a.get("type", ""), "href": a.get("href"), "checked": "checked" in a, "options": [],
                  "form": dict(self.form) if self.form else None, "irreversible": a.get("data-irreversible") == "1",
                  "submit": tag == "button" and a.get("type", "submit") == "submit" or a.get("type") == "submit", "label": None}  # fmt: skip
            if self.label_stack:
                el["label"] = self.label_stack[-1]
            self.els.append(el)
            if tag in ("a", "button", "select", "textarea"):
                self._open_el = el

    def handle_endtag(self, tag: str) -> None:
        while self.stack:
            top = self.stack.pop()
            if top.get("hidden_marker"):
                self.hidden_depth -= 1
            if top["tag"] == tag:
                break
        if tag == "title":
            self._in_title = False
        if tag == "form":
            self.form = None
        if tag == "label" and self.label_stack:
            lb = self.label_stack.pop()
            if lb["for"]:
                self.labels[lb["for"]] = lb["text"].strip()
            for e in self.els:
                if e["label"] is lb and not e["name"]:
                    e["name"] = lb["text"].strip()
        if self._open_el is not None and tag == self._open_el["tag"]:
            self._open_el = None

    def handle_data(self, data: str) -> None:
        d = data.strip()
        if not d:
            return
        if self.hidden_depth:
            self.hidden_text.append(d)
            return
        if self._in_title:
            self.title += d
            return
        for lb in self.label_stack:
            lb["text"] += " " + d
        if self._open_el is not None:
            if self._open_el["tag"] == "select" and self.stack and self.stack[-1]["tag"] == "option":
                self._open_el["options"].append(d)
            elif self._open_el["tag"] != "select":
                self._open_el["name"] = (self._open_el["name"] + " " + d).strip()
            return
        self.texts.append(d)


def parse(page: str) -> dict[str, Any]:
    p = _Parser()
    p.feed(page)
    for e in p.els:
        if not e["name"] and e["id"] in p.labels:
            e["name"] = p.labels[e["id"]]
        if e["role"] == "combobox" and not e["value"] and e["options"]:
            e["value"] = e["options"][0]
        e.pop("label", None)
    alerts = re.findall(r'<div role="alert">(.*?)</div>', page)
    return {"title": p.title, "elements": p.els, "text": p.texts, "hidden_text": p.hidden_text, "alerts": alerts}


class SimBrowser:
    def __init__(self, site: str, start: str, state: dict[str, Any] | None = None, allowed: tuple[str, ...] | None = sites.ALLOWED):
        self.state = state or sites.initial(site)
        self.url = start
        self.allowed = allowed
        self.history: list[str] = []
        self.values: dict[int, str] = {}
        self._load()

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "url": self.url,
            "history": self.history,
            "values": {str(k): v for k, v in self.values.items()},
            "allowed": list(self.allowed or []),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SimBrowser:
        b = cls.__new__(cls)
        b.state, b.url, b.history, b.allowed = d["state"], d["url"], d["history"], tuple(d["allowed"]) or None
        b.values = {}
        b._load(keep_flash=True)
        b.values = {int(k): v for k, v in d["values"].items()}
        return b

    def _load(self, keep_flash: bool = False) -> None:
        flash = self.state.get("flash", "")
        self.page = parse(sites.render(self.state, self.url))
        if keep_flash:
            self.state["flash"] = flash
        self.values = {}

    def _host(self, url: str) -> str:
        return url.removeprefix("http://").split("/")[0]

    def _abs(self, href: str) -> str:
        return href if href.startswith("http") else f"http://{self._host(self.url)}{href}"

    def tree(self) -> str:
        """에이전트가 보는 화면 — 역할 · 이름 · 값 · 번호. 숨은 글은 넣지 않는다."""
        lines = [f"주소: {self.url}", f"제목: {self.page['title']}"]
        lines += [f"알림: {a}" for a in self.page["alerts"]]
        lines += [f"글: {t}" for t in self.page["text"][:30]]
        for e in self.page["elements"]:
            v = self.values.get(e["eid"], e["value"])
            extra = f" 값='{v}'" if e["role"] in ("textbox", "combobox") and v else ""
            if e["role"] in ("checkbox", "radio"):
                extra = f" {'선택됨' if self.values.get(e['eid'], 'on' if e['checked'] else '') == 'on' else '선택 안 됨'}"
            if e["role"] == "combobox":
                extra += f" 선택지={e['options']}"
            if e["role"] == "link":
                extra += f" → {e['href']}"
            lines.append(f"[{e['eid']}] {e['role']} '{e['name']}'{extra}")
        return "\n".join(lines)

    def fingerprint(self) -> str:
        return hashlib.sha1((self.url + self.tree()).encode()).hexdigest()[:12]

    def element(self, eid: int) -> dict[str, Any] | None:
        return next((e for e in self.page["elements"] if e["eid"] == eid), None)

    def is_risky(self, act: dict[str, Any]) -> str | None:
        """되돌릴 수 없는 행동인가 — 사이트가 표시한 버튼(data-irreversible) 또는 이름 규칙(제출 · 결제 · 삭제 · 보내기)."""
        if act.get("action") != "click":
            return None
        e = self.element(int(act.get("eid") or 0))
        if not e:
            return None
        # 이름 규칙은 버튼에만 — 링크 '새 티켓 접수' 처럼 이동만 하는 요소까지 승인을 요구하면 쓸데없이 멈춘다
        if e["irreversible"] or (e["role"] == "button" and re.search(r"삭제|결제|송금|보내기|전송|제출|접수|확정", e["name"])):
            return e["name"]
        return None

    def act(self, a: dict[str, Any]) -> dict[str, Any]:
        """행동 하나 → {"ok", "error", "changed", "alerts"}. 허용 밖 도메인은 이동하지 않는다."""
        before = self.fingerprint()
        kind = a.get("action")
        err = None
        if kind == "navigate":
            url = str(a.get("url", ""))
            if self.allowed and self._host(url) not in self.allowed:
                return {"ok": False, "error": f"허용 밖 도메인 {self._host(url)} — 이동하지 않음", "changed": False, "blocked": True}
            self.history.append(self.url)
            self.url = url
            self._load()
        elif kind == "back":
            if self.history:
                self.url = self.history.pop()
                self._load()
        elif kind in ("click", "type", "select", "check"):
            e = self.element(int(a.get("eid") or 0))
            if e is None:
                return {"ok": False, "error": f"요소 [{a.get('eid')}] 가 화면에 없습니다", "changed": False}
            if kind == "type":
                if e["role"] != "textbox":
                    return {"ok": False, "error": f"[{e['eid']}] 는 입력란이 아닙니다({e['role']})", "changed": False}
                self.values[e["eid"]] = str(a.get("text", ""))
            elif kind == "select":
                v = str(a.get("value", ""))
                if v not in e["options"]:
                    return {"ok": False, "error": f"선택지에 없는 값 '{v}' — {e['options']}", "changed": False}
                self.values[e["eid"]] = v
            elif kind == "check":
                if e["role"] == "radio":
                    for o in self.page["elements"]:
                        if o["role"] == "radio" and o["field"] == e["field"]:
                            self.values[o["eid"]] = ""
                self.values[e["eid"]] = "on"
            elif e["role"] == "link":
                url = self._abs(e["href"] or "")
                if self.allowed and self._host(url) not in self.allowed:
                    return {
                        "ok": False,
                        "error": f"허용 밖 도메인 {self._host(url)} 링크 — 이동하지 않음",
                        "changed": False,
                        "blocked": True,
                    }
                self.history.append(self.url)
                self.url = url
                self._load()
            elif e["submit"] and e["form"] is not None:
                fields = self._fields(e["form"])
                self.history.append(self.url)
                self.url = sites.submit(self.state, self.url, e["form"]["action"], fields)
                self._load()
            else:
                err = "누를 수 없는 요소입니다"
        else:
            return {"ok": False, "error": f"알 수 없는 행동: {kind}", "changed": False}
        after = self.fingerprint()
        return {"ok": err is None, "error": err, "changed": before != after, "alerts": self.page["alerts"], "url": self.url}

    def _fields(self, form: dict[str, Any]) -> dict[str, str]:
        out = {}
        for e in self.page["elements"]:
            if not e["form"] or e["form"]["id"] != form["id"] or not e["field"]:
                continue
            v = self.values.get(e["eid"])
            if e["role"] in ("checkbox", "radio"):
                on = (v == "on") if v is not None else e["checked"]
                if on:
                    out[e["field"]] = e["value"] or "on"
            else:
                out[e["field"]] = v if v is not None else e["value"]
        return out
