"""엔터프라이즈 플랫폼(PF1~PF7): 속도 제한 · 테넌트 격리 · 프롬프트 레지스트리 · 기능 플래그 · 장애 대응 · 비용 배분.

여기서 바꾸는 것은 모두 전역이다(속도 제한 창 · 활성 프롬프트 · 플래그 · 차단기 · 테넌트 묶음 · 예산) — 서비스 전체 동작이
배포 없이 바뀌는 것이 이 맵의 목적이라서. 그래서 테스트마다 만든 행 · 메모리 상태를 되돌려 다른 테스트에 새지 않게 한다.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.core import llm, tracing
from app.core.auth import User
from app.core.config import get_settings
from app.core.db import PfBudget, PfFlag, PfPrompt, SessionLocal
from app.pipeline import serve
from app.pipeline.search import default_config, run_search
from app.stages.platform import chargeback, gateway, registry, resilience, tenancy

LCFG = llm.LLMConfig("openai", "fake", "http://local/v1")


@pytest.fixture
def clean_gateway(monkeypatch):
    """속도 제한 창 · 사용량은 모듈 전역 — 새 그릇으로 바꿔 두면 테스트가 끝날 때 원래대로 돌아간다."""
    monkeypatch.setattr(gateway, "_windows", {})
    monkeypatch.setattr(gateway, "_usage", gateway.Counter())
    monkeypatch.setattr(gateway, "_denied", gateway.Counter())


@pytest.fixture
def clean_registry():
    yield
    with SessionLocal() as db:
        db.execute(delete(PfPrompt).where(PfPrompt.name.in_(["answer_system", "test_prompt"])))
        db.execute(delete(PfFlag).where(PfFlag.key.in_(["guard_mode", "ai_notice"])))
        db.commit()
    registry.invalidate()  # 10초 기억 — 지운 뒤 바로 코드 기본값이 보이게


@pytest.fixture
def fresh_breaker(monkeypatch):
    monkeypatch.setattr(resilience, "BREAKER", resilience.Breaker())
    return resilience.BREAKER


# ── PF1 게이트웨이 ──────────────────────────────────────────────────────────
def test_route_group():
    assert gateway.route_group("/api/rag/answer/stream") == "rag" and gateway.route_group("/mcp/x") == "mcp"
    assert gateway.route_group("/rag/collections") == "page" and gateway.route_group("/") == "page"


def test_rate_limit_sliding_window_per_key(clean_gateway, monkeypatch):
    st = get_settings()
    monkeypatch.setattr(st, "rate_limit_per_min", 2)
    monkeypatch.setattr(st, "rate_limit_overrides", {"vip": 5, "tenant:acme": 3})
    assert gateway.limit_for("kim", "공용") == 2 and gateway.limit_for("vip", "acme") == 5 and gateway.limit_for("lee", "acme") == 3
    t0 = 1000.0
    assert gateway.check("kim", "공용", "/api/rag/search", now=t0) == (True, 0)
    assert gateway.check("kim", "공용", "/api/rag/search", now=t0 + 1)[0]
    ok, retry = gateway.check("kim", "공용", "/api/rag/search", now=t0 + 10)
    assert not ok and retry == 51  # 가장 오래된 요청이 창(60초)에서 빠질 때까지
    # 한 사용자가 몰아 불러도 다른 사용자 · 같은 이름의 다른 테넌트는 막히지 않는다
    assert gateway.check("park", "공용", "/api/rag/search", now=t0 + 10)[0]
    assert gateway.check("kim", "acme", "/api/rag/search", now=t0 + 10)[0]
    assert gateway.check("kim", "공용", "/api/rag/search", now=t0 + 61)[0]  # 60초 지나면 다시
    assert gateway.check("kim", "공용", "/static/app.js", now=t0 + 61) == (True, 0)  # 정적 파일 · 상태 확인은 세지 않음
    u = gateway.usage()
    assert u["denied"] == {"공용:kim": 1} and {"tenant": "공용", "user": "kim", "route": "rag", "n": 4} in u["rows"]


def test_rate_limit_zero_means_off(clean_gateway, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_min", 0)
    monkeypatch.setattr(get_settings(), "rate_limit_overrides", {})
    assert all(gateway.check("kim", "공용", "/api/x", now=1.0)[0] for _ in range(50))


def test_middleware_429_uses_authenticated_user(client, clean_gateway, monkeypatch):
    """속도 제한은 인증이 사용자를 정한 뒤 센다(미들웨어 등록 순서) — 그래야 사용자 · 테넌트별 제한이 된다. 넘으면 429 + Retry-After."""
    st = get_settings()
    monkeypatch.setattr(st, "api_users", [{"name": "kim", "token": "tk-kim", "groups": ["tenant:acme"]},
                                          {"name": "lee", "token": "tk-lee", "groups": ["tenant:beta"]}])  # fmt: skip
    monkeypatch.setattr(st, "rate_limit_per_min", 0)
    monkeypatch.setattr(st, "rate_limit_overrides", {"kim": 2})
    kim, lee = {"Authorization": "Bearer tk-kim"}, {"Authorization": "Bearer tk-lee"}
    assert [client.get("/api/platform/gateway", headers=kim).status_code for _ in range(2)] == [200, 200]
    r = client.get("/api/platform/gateway", headers=kim)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1 and "분당 2회" in r.json()["detail"]
    assert client.get("/api/platform/gateway", headers=lee).status_code == 200  # 다른 사용자는 그대로
    usage = client.get("/api/platform/gateway", headers=lee).json()
    assert usage["denied"] == {"acme:kim": 1} and usage["auth"]


# ── PF2 테넌트 격리 ─────────────────────────────────────────────────────────
@pytest.fixture
def tenant_col(client, rag_collection):
    cid = rag_collection["cid"]
    yield cid
    with SessionLocal() as db:
        tenancy.assign(db, cid, None)  # 컬렉션 번호는 다시 쓰이므로 묶음을 남기면 다음 컬렉션이 남의 테넌트가 된다


def test_tenant_isolation_in_search(client, tenant_col):
    cid = tenant_col
    with SessionLocal() as db:
        cfg = default_config(db, cid)
        q = "세탁기 배수가 안 될 때"
        assert run_search(db, q, cfg | {"acl_groups": ["tenant:beta"]})["results"]  # 묶기 전에는 공용
    r = client.post("/api/platform/tenants", json={"collection_id": cid, "tenant": "acme"})
    assert r.json() == {"collection_id": cid, "tenant": "acme"}
    with SessionLocal() as db:
        other = run_search(db, q, cfg | {"acl_groups": ["tenant:beta", "sales"]})
        # 다른 테넌트는 검색 전에 막혀 LLM 이 읽을 근거 자체가 없다 · 무엇 때문에 막혔는지 남긴다
        assert other["results"] == [] and other["restricted"]["tenant"]["owner"] == "acme"
        assert run_search(db, q, cfg | {"acl_groups": ["tenant:acme"]})["results"]
        assert run_search(db, q, cfg | {"acl_groups": ["*"]})["results"]  # 전체 권한(관리자 · 로컬)은 모두 본다
        assert tenancy.blocked(db, cid, ["tenant:beta"]) == "acme" and tenancy.blocked(db, cid, ["tenant:acme"]) is None
    ov = client.get("/api/platform/tenants").json()
    assert {"collection_id": cid, "name": "후반 단계 테스트", "tenant": "acme"} in ov["collections"]


def test_leak_test_and_unassign(client, tenant_col):
    other = client.post("/api/collections", json={"name": "다른 테넌트 자료"}).json()["id"]
    try:
        client.post("/api/platform/tenants", json={"collection_id": tenant_col, "tenant": "acme"})
        client.post("/api/platform/tenants", json={"collection_id": other, "tenant": "beta"})
        r = client.post("/api/platform/tenants/leak-test", json={"queries": ["세탁기 배수", "공문서"]}).json()
        assert {"acme", "beta"} <= set(r["tenants"]) and r["leaks"] == 0
        assert {"as": "beta", "collection_id": tenant_col, "owner": "acme", "results": 0, "leak": False} in r["rows"]
        client.post("/api/platform/tenants", json={"collection_id": tenant_col, "tenant": ""})  # 비우면 공용으로
        with SessionLocal() as db:
            assert tenancy.collection_tenant(db, tenant_col) is None
    finally:
        with SessionLocal() as db:
            tenancy.assign(db, other, None)
        client.delete(f"/api/collections/{other}")
    assert client.post("/api/platform/tenants", json={"collection_id": 99999999, "tenant": "x"}).status_code == 404


def test_tenant_of_trace():
    assert tenancy.tenant_of_trace(["sales", "tenant:b", "tenant:a"]) == "a" and tenancy.tenant_of_trace(None) == "공용"


def test_admin_only_changes(client, monkeypatch):
    """테넌트 · 프롬프트 · 플래그 · 예산은 서비스 동작을 바로 바꾸므로 관리자만."""
    monkeypatch.setattr(get_settings(), "api_users", [{"name": "kim", "token": "tk", "groups": ["tenant:acme"], "role": "user"}])
    h = {"Authorization": "Bearer tk"}
    assert client.post("/api/platform/tenants", json={"collection_id": 1, "tenant": "x"}, headers=h).status_code == 403
    assert client.post("/api/platform/prompts", json={"name": "answer_system", "text": "x" * 20}, headers=h).status_code == 403
    assert client.post("/api/platform/flags/guard_mode", json={"default": "off"}, headers=h).status_code == 403
    assert client.post("/api/platform/budgets", json={"tenant": "acme", "monthly_usd": 1}, headers=h).status_code == 403


# ── PF3 프롬프트 레지스트리 ─────────────────────────────────────────────────
def test_prompt_versions_single_active(client, clean_registry):
    a = client.post("/api/platform/prompts", json={"name": "test_prompt", "text": "첫 번째 판 프롬프트입니다", "activate": True}).json()
    b = client.post("/api/platform/prompts", json={"name": "test_prompt", "text": "두 번째 판 프롬프트입니다"}).json()
    assert (a["version"], b["version"]) == (1, 2) and a["active"] and not b["active"]
    with SessionLocal() as db:
        assert registry.active_prompt(db, "test_prompt") == ("첫 번째 판 프롬프트입니다", 1)
    client.post("/api/platform/prompts/test_prompt/activate", json={"version": 2})
    with SessionLocal() as db:  # 바꾸면 기억(10초)을 비워 바로 적용
        assert registry.active_prompt(db, "test_prompt") == ("두 번째 판 프롬프트입니다", 2)
    vs = [v for v in client.get("/api/platform/prompts").json()["versions"] if v["name"] == "test_prompt"]
    assert [v["active"] for v in vs] == [True, False]  # 하나만 활성
    assert client.post("/api/platform/prompts/test_prompt/activate", json={"version": 9}).status_code == 404
    client.post("/api/platform/prompts/test_prompt/activate", json={"version": None})
    with SessionLocal() as db:
        assert registry.active_prompt(db, "test_prompt") is None  # 활성 없음 → 코드 기본값


def test_serve_uses_active_prompt_and_records_version(client, rag_collection, clean_registry, monkeypatch, fresh_breaker):
    """서비스 답변은 활성 프롬프트를 쓰고 요청 기록에 '이름@버전'을 남긴다 — 품질이 떨어지면 어느 버전부터인지 찾으려고."""
    systems = []
    monkeypatch.setattr(
        llm, "chat", lambda cfg, system, user, *a, **k: systems.append(system) or {"text": "배수 필터를 청소하세요 [1].", "usage": {}}
    )
    with SessionLocal() as db:
        cfg = default_config(db, rag_collection["cid"])
        r = serve.answer_once(db, "세탁기 배수가 안 될 때", cfg, LCFG, mode="off")
        assert r["signals"]["prompt"] == "answer_system@code"
        registry.add_prompt(db, "answer_system", "회사 규정 프롬프트 — 반드시 근거 번호를 붙입니다.", "", "local", activate=True)
        r = serve.answer_once(db, "세탁기 배수가 안 될 때", cfg, LCFG, mode="off")
        assert r["signals"]["prompt"] == "answer_system@1" and systems[-1].startswith("회사 규정 프롬프트")
        registry.set_active(db, "answer_system", None)  # 되돌리기 = 이전(코드) 활성으로
        r = serve.answer_once(db, "세탁기 배수가 안 될 때", cfg, LCFG, mode="off")
        assert r["signals"]["prompt"] == "answer_system@code" and "회사 규정" not in systems[-1]


# ── PF4 기능 플래그 ─────────────────────────────────────────────────────────
def test_flag_rules_first_match_and_pct_sticky(client, clean_registry):
    rules = [{"user": "boss", "value": "off"}, {"tenant": "acme", "value": "enforce"}, {"group": "qa", "pct": 50, "value": "mask"}]
    assert client.post("/api/platform/flags/guard_mode", json={"default": "mask", "rules": rules}).status_code == 200
    ev = lambda user, groups: client.post("/api/platform/flags/guard_mode/eval", json={"user": user, "groups": groups}).json()["value"]  # noqa: E731
    assert ev("boss", ["tenant:acme"]) == "off"  # 첫 번째로 맞는 규칙
    assert ev("kim", ["tenant:acme"]) == "enforce" and ev("kim", ["sales"]) == "mask"
    with SessionLocal() as db:
        names = [f"u{i}" for i in range(200)]
        inside = [n for n in names if registry.matches({"pct": 50}, User(n, ("qa",), "user"), "guard_mode")]
        assert 60 < len(inside) < 140  # 대략 절반
        # 같은 사용자는 늘 같은 값 — 요청마다 바뀌면 같은 사람이 두 동작을 번갈아 본다
        assert all(registry.matches({"pct": 50}, User(n, ("qa",), "user"), "guard_mode") for n in inside)
        assert registry.flag(db, "no_such_flag", User("kim")) is None  # 플래그 없음 → 부르는 쪽이 설정값
    bad = client.post("/api/platform/flags/guard_mode", json={"rules": [{"country": "kr", "value": 1}]})
    assert bad.status_code == 400
    f = next(x for x in client.get("/api/platform/flags").json()["flags"] if x["key"] == "guard_mode")
    assert f["default"] == "mask" and len(f["history"]) == 1 and f["history"][0]["after"]["rules"] == rules
    assert {x["key"] for x in client.get("/api/platform/flags").json()["flags"]} >= set(registry.KNOWN_FLAGS)


def test_flag_turns_off_ai_notice_in_serve(client, rag_collection, clean_registry, monkeypatch, fresh_breaker):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"text": "배수 필터를 청소하세요 [1].", "usage": {}})
    with SessionLocal() as db:
        cfg = default_config(db, rag_collection["cid"])
        assert serve.answer_once(db, "세탁기 배수가 안 될 때", cfg, LCFG, mode="off")["notice"]
        registry.set_flag(db, "ai_notice", None, [{"user": "local", "value": False}], "", "local")
        r = serve.answer_once(db, "세탁기 배수가 안 될 때", cfg, LCFG, mode="off")
        assert r["notice"] == "" and r["guard"]["notice"] is False


# ── PF6 장애 대응 ───────────────────────────────────────────────────────────
def test_breaker_opens_after_fails_and_half_opens(fresh_breaker, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(resilience.time, "monotonic", lambda: clock[0])
    b = fresh_breaker
    for _ in range(resilience.FAILS - 1):
        b.fail("k", "끊김")
    assert b.allow("k")
    b.fail("k", "끊김")
    assert not b.allow("k") and b.out()["k"]["open"]  # 연달아 실패하면 기다리지 않고 바로 대체로
    clock[0] += resilience.COOL
    assert b.allow("k")  # 반쯤 열림 — 한 번 시험
    b.ok("k")
    assert b.allow("k") and b.out()["k"] == {"fails": 0, "open": False, "last_error": "끊김"}


@pytest.fixture
def fallbacks(monkeypatch):
    st = get_settings()
    monkeypatch.setattr(st, "llm_provider", None)
    monkeypatch.setattr(st, "openai_model", "main")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")
    monkeypatch.setattr(st, "llm_fallbacks", [{"provider": "openai", "model": "main"},  # 주 모델과 같으면 빠짐
                                              {"provider": "openai", "model": "backup", "base_url": "http://backup/v1/"},
                                              {"provider": "nope", "model": "x"}])  # fmt: skip
    return llm.resolve()


def test_chain_dedups_and_skips_unresolvable(fallbacks):
    c = resilience.chain(fallbacks)
    assert [(x.model, x.base_url) for x in c] == [("main", "http://local/v1"), ("backup", "http://backup/v1")]


def test_chat_falls_back_and_skips_open_breaker(fallbacks, fresh_breaker, monkeypatch):
    calls = []

    def chat(cfg, *a, **k):
        calls.append(cfg.model)
        if cfg.model == "main":
            raise llm.LLMError("주 서버 끊김")
        return {"text": "대체 답"}

    monkeypatch.setattr(llm, "chat", chat)
    r, used, skipped = resilience.chat(fallbacks, "s", "u")
    assert r["text"] == "대체 답" and used.model == "backup" and skipped[0].startswith("main(주 서버 끊김")
    for _ in range(resilience.FAILS):
        resilience.chat(fallbacks, "s", "u")
    calls.clear()
    _, used, skipped = resilience.chat(fallbacks, "s", "u")
    # 차단기가 열린 주 모델은 부르지도 않는다 — 죽은 서버의 시간 초과(120초)를 매번 기다리지 않게
    assert calls == ["backup"] and skipped == ["main(차단기 열림)"]

    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("모두 끊김")))
    with pytest.raises(llm.LLMError, match="모두 끊김"):
        resilience.chat(fallbacks, "s", "u")


def test_serve_records_fallback(client, rag_collection, fallbacks, fresh_breaker, monkeypatch):
    """대체 모델로 답했으면 요청 기록에 남긴다 — 같은 품질이 아니라는 것을 숨기지 않는다."""

    def chat(cfg, *a, **k):
        if cfg.model == "main":
            raise llm.LLMError("주 서버 끊김")
        return {"text": "배수 필터를 청소하세요 [1].", "usage": {}}

    monkeypatch.setattr(llm, "chat", chat)
    with SessionLocal() as db:
        r = serve.answer_once(db, "세탁기 배수가 안 될 때", default_config(db, rag_collection["cid"]), fallbacks, mode="off")
    assert r["guard"]["fallback"]["from"] == "main" and r["guard"]["fallback"]["to"] == "backup"


def test_ops_lists_chain_and_breakers(client, fallbacks, fresh_breaker):
    fresh_breaker.fail("llm:openai:main@http://local/v1", "x")
    r = client.get("/api/platform/ops").json()
    assert [c["model"] for c in r["llm_chain"]] == ["main", "backup"] and r["breakers"]["llm:openai:main@http://local/v1"]["fails"] == 1
    assert r["migration"] == r["migrations_in_repo"]  # 앱이 저장소의 마지막 마이그레이션까지 적용했다


# ── PF7 비용 배분 ───────────────────────────────────────────────────────────
@pytest.fixture
def tenant_name():
    name = f"pf-{uuid.uuid4().hex[:8]}"  # 요청 기록은 지울 수 없으므로(해시 사슬) 테스트마다 새 테넌트로 센다
    yield name
    with SessionLocal() as db:
        db.execute(delete(PfBudget).where(PfBudget.tenant == name))
        db.commit()


def test_chargeback_by_tenant_and_budget_alert_once(client, tenant_name):
    with SessionLocal() as db:
        for kind, cost in (("answer", 0.3), ("answer", 0.2), ("as", 0.4)):
            tracing.record(db, kind=kind, user="kim", groups=[f"tenant:{tenant_name}", "sales"], question="q", answer="a", tokens_in=100,
                           tokens_out=20, cost=cost, total_ms=10.0)  # fmt: skip
    r = client.post("/api/platform/budgets", json={"tenant": tenant_name, "monthly_usd": 1.0, "alert_pct": 80}).json()
    assert r == {"tenant": tenant_name, "monthly_usd": 1.0, "alert_pct": 80}
    rep = client.get("/api/platform/chargeback").json()
    rows = {r["kind"]: r for r in rep["rows"] if r["tenant"] == tenant_name}
    assert rows["answer"]["requests"] == 2 and rows["answer"]["tokens"] == 240 and rows["answer"]["cost"] == pytest.approx(0.5)
    t = next(x for x in rep["tenants"] if x["tenant"] == tenant_name)
    assert t["requests"] == 3 and t["used_pct"] == 90.0 and t["over_alert"]
    with SessionLocal() as db:
        first = [a for a in chargeback.alerts(db) if a.get("tenant") == tenant_name]
        assert len(first) == 1 and "90.0%" in first[0]["message"]
        assert not [a for a in chargeback.alerts(db) if a.get("tenant") == tenant_name]  # 같은 달에는 한 번만
        # 지난달 기록은 이번 달 보고에 들지 않는다
        later = chargeback.report(db, since=datetime(2999, 1, 1, tzinfo=UTC))
        assert not [x for x in later["rows"] if x["tenant"] == tenant_name]


def test_month_start():
    assert chargeback.month_start(datetime(2026, 3, 17, 9, 30, tzinfo=UTC)) == datetime(2026, 3, 1, tzinfo=UTC)
