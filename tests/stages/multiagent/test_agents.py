"""멀티에이전트 전문가들(MA2 · MA4 · MA5 · MA6 · MA7 · MA8)을 하나씩: 검색(Self-RAG) · 분석 · 작성 · 검증 · 출력.

LLM · 샌드박스 · TTS 는 모두 가짜로 바꾼다 — 각 에이전트가 '언제 무엇을 부르고 언제 멈추는지'가 설계의 핵심이라
그 판단만 결정적으로 본다.
"""

import itertools
import json

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.stages.multiagent import analysis, critic, output, retrieval, writer

LCFG = llm.LLMConfig("openai", "fake-big", "http://local/v1")
AS_TEXT = "세탁기 배수가 안 될 때는 배수 필터를 청소하세요. 냉장고 소음은 수평 조절로 줄일 수 있습니다."


def _src(i, text, **kw):
    return {"chunk_id": i, "document_id": i, "filename": f"d{i}.txt", "text": text} | kw


@pytest.fixture(autouse=True)
def _no_relevance(monkeypatch):
    # 질문 관련성 검사는 임베딩 모델을 부른다 — 여기서는 근거 일치 · 정책 판단만 보려고 끈다(관련성은 RAG 검증 테스트가 본다)
    monkeypatch.setattr(get_settings(), "answer_relevance", False)


# ── MA4 Self-RAG ─────────────────────────────────────────────────────────────
def test_keywords_drop_particles_and_stopwords():
    # 조사 · 의문 낱말이 남으면 '덮음'이 근거와 상관없이 낮아져 멀쩡한 검색도 '부족'으로 판정된다
    assert retrieval.keywords("세탁기 배수가 무엇 알려 주세요") == ["세탁기", "배수"]


def test_sufficient_rule_decides_without_llm_when_clear(monkeypatch):
    """규칙이 분명하면(덮음 ≥ 0.85 · < 0.3 · 결과 없음) LLM 판정을 부르지 않는다 — 판정 한 번이 검색보다 비싸기 때문."""

    def boom(*a, **k):
        raise AssertionError("규칙으로 끝나야 한다")

    monkeypatch.setattr(llm, "chat_json", boom)
    assert retrieval.sufficient("세탁기 배수", [], LCFG) == {"enough": False, "coverage": 0.0, "by": "rule", "missing": "검색 결과 없음"}
    full = retrieval.sufficient("세탁기 배수", [_src(1, AS_TEXT)], LCFG)
    assert full["enough"] and full["by"] == "rule" and full["coverage"] == 1.0
    low = retrieval.sufficient("보증금 반환 계약 해지 위약금", [_src(1, AS_TEXT)], LCFG)
    assert not low["enough"] and low["by"] == "rule"


def test_sufficient_uses_llm_only_in_ambiguous_band(monkeypatch):
    calls = []

    def judge(cfg, system, user, **kw):
        calls.append(system)
        return {"enough": False, "missing": "냉장고 모델명"}, {}

    monkeypatch.setattr(llm, "chat_json", judge)
    # 핵심 낱말 3개 중 2개만 근거에 있음(0.667) — 규칙으로 가를 수 없는 구간
    r = retrieval.sufficient("세탁기 배수 보증기간", [_src(1, AS_TEXT)], LCFG)
    assert r == {"enough": False, "coverage": 0.667, "by": "llm", "missing": "냉장고 모델명"} and calls == [retrieval.JUDGE]
    # 판정할 LLM 이 없으면 같은 덮음이라도 규칙(min_cov 0.6)으로
    assert retrieval.sufficient("세탁기 배수 보증기간", [_src(1, AS_TEXT)], None) == {"enough": True, "coverage": 0.667, "by": "rule"}


def test_sufficient_falls_back_to_rule_when_judge_breaks(monkeypatch):
    def bad(*a, **k):
        raise llm.LLMError("서버 끊김")

    monkeypatch.setattr(llm, "chat_json", bad)
    r = retrieval.sufficient("세탁기 배수 보증기간", [_src(1, AS_TEXT)], LCFG)
    assert r["by"] == "rule" and r["enough"]  # 판정이 실패해도 검색 전체를 멈추지 않는다


def test_self_rag_rewrites_until_round_limit(monkeypatch):
    """근거가 계속 부족하면 질의를 고쳐 다시 찾되 상한(rounds)에서 멈춘다 — 끝없는 재검색으로 비용 · 지연이 커지지 않게."""
    queries, counter = [], itertools.count()
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: ({"enough": False, "missing": "더"}, {}))
    monkeypatch.setattr(retrieval.enhance, "generate", lambda tech, q, cfg, n=1: {"variants": [{"text": f"고친 질의 {next(counter)}"}]})

    def search(q):
        queries.append(q)
        # 같은 청크(1)는 매번 나오고 새 청크가 하나씩 — 풀에는 중복 없이 쌓여야 한다
        return [_src(1, "세탁기 이야기"), _src(len(queries) + 1, "배수 이야기")]

    r = retrieval.self_rag("세탁기 배수 보증기간", search, LCFG, rounds=3)
    assert len(r["rounds"]) == 3 and len(queries) == 3 and not r["enough"]
    assert queries[0] == "세탁기 배수 보증기간" and queries[1:] == ["고친 질의 0", "고친 질의 1"]
    ids = [s["chunk_id"] for s in r["sources"]]
    assert ids == sorted(set(ids)) and len(ids) == 4  # 1 + 라운드마다 새 청크 하나
    assert [s["round"] for s in r["sources"]] == [1, 1, 2, 3]


def test_self_rag_stops_when_enough_or_rewrite_repeats(monkeypatch):
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: ({"enough": False}, {}))
    called = []
    r = retrieval.self_rag("세탁기 배수", lambda q: called.append(q) or [_src(1, AS_TEXT)], LCFG, rounds=3)
    assert r["enough"] and len(called) == 1  # 첫 검색이 충분하면 다시 찾지 않는다

    # 재작성이 같은 질의를 돌려주면 같은 검색을 되풀이하지 않고 멈춘다
    monkeypatch.setattr(retrieval.enhance, "generate", lambda tech, q, cfg, n=1: {"variants": [{"text": "세탁기 배수 보증기간"}]})
    called.clear()
    r = retrieval.self_rag("세탁기 배수 보증기간", lambda q: called.append(q) or [_src(1, AS_TEXT)], LCFG, rounds=3)
    assert len(called) == 1 and len(r["rounds"]) == 1

    # LLM 이 없으면 고칠 수단이 없으므로 한 번만
    called.clear()
    retrieval.self_rag("보증금 반환 위약금", lambda q: called.append(q) or [_src(1, AS_TEXT)], None, rounds=3)
    assert len(called) == 1


def test_vision_rerank_moves_scored_images_forward(monkeypatch):
    """그림 청크만 비전 LLM 점수로 앞으로 — 글 임베딩이 그림 속 정보를 놓치는 경우를 보완. 글 청크 순서는 그대로."""
    monkeypatch.setattr(retrieval.media_store, "resolve", lambda rel: type("P", (), {"read_bytes": lambda self: b"jpeg"})())
    seen = []

    def judge(cfg, system, user, images=None, **kw):
        seen.append(images)
        return {"score": 3}, {}

    monkeypatch.setattr(llm, "chat_json", judge)
    srcs = [_src(1, "글 1"), _src(2, "글 2"), _src(3, "그림", media={"url": "/m/3"}, media_rel="3.jpg")]
    out = retrieval.vision_rerank("배수 필터 위치", srcs, LCFG)
    assert [s["chunk_id"] for s in out] == [3, 1, 2] and out[0]["vision_score"] == 3 and seen == [[b"jpeg"]]
    assert retrieval.vision_rerank("q", srcs[:2], None) == srcs[:2]


def test_vision_rerank_keeps_order_on_error(monkeypatch):
    monkeypatch.setattr(retrieval.media_store, "resolve", lambda rel: type("P", (), {"read_bytes": lambda self: b"x"})())
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("비전 아님")))
    srcs = [_src(1, "글"), _src(2, "그림", media={"url": "/m"}, media_rel="2.jpg")]
    assert [s["chunk_id"] for s in retrieval.vision_rerank("q", srcs, LCFG)] == [1, 2]


# ── MA5 분석 ────────────────────────────────────────────────────────────────
def test_analysis_needed_only_for_numeric_questions():
    assert analysis.needed("지난달 대비 증가 비율은?") and analysis.needed("부서별 합계 표로")
    assert not analysis.needed("세탁기 배수가 안 될 때")


def test_analysis_retries_with_error_feedback_and_validates_chart(monkeypatch):
    """LLM 은 코드만 쓰고 계산은 샌드박스가 — 첫 코드가 실패하면 오류를 되먹여 다시 쓰게 하고, 차트는 labels · values 길이가 맞을 때만."""
    prompts, runs = [], []

    def chat(cfg, system, user, **kw):
        prompts.append(user)
        return {"text": "```python\nprint('a')\n```" if len(prompts) == 1 else "```python\nprint('b')\n```"}

    def run_python(code):
        runs.append(code)
        assert code.startswith("import json, re, math, statistics\nSOURCES = ")  # 근거 글이 코드 입력으로 들어간다
        if code.endswith("print('a')"):
            return {"stdout": "", "stderr": "NameError: x", "exit_code": 1, "isolation": "fake"}
        out = {"result": "합계 30", "chart": {"type": "bar", "labels": ["a", "b"], "values": [10, 20, 30]}}
        return {"stdout": "계산 중\n" + json.dumps(out, ensure_ascii=False), "stderr": "", "exit_code": 0, "isolation": "fake"}

    monkeypatch.setattr(llm, "chat", chat)
    monkeypatch.setattr(analysis.sandbox, "run_python", run_python)
    r = analysis.run("합계는?", [_src(1, "A 10, B 20")], LCFG, retries=1)
    assert r["ok"] and r["result"] == "합계 30" and r["chart"] is None  # 길이가 안 맞는 차트는 버린다
    assert len(r["attempts"]) == 2 and "NameError" in prompts[1] and "앞선 시도 오류" in prompts[1]


def test_analysis_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"text": "print(1)"})
    monkeypatch.setattr(
        analysis.sandbox, "run_python", lambda code: {"stdout": "숫자 없음", "stderr": "", "exit_code": 0, "isolation": "fake"}
    )
    r = analysis.run("합계는?", [_src(1, "x")], LCFG, retries=2)
    assert not r["ok"] and r["result"] is None and len(r["attempts"]) == 3


# ── MA6 작성 ────────────────────────────────────────────────────────────────
def test_writer_routes_easy_to_small_model_and_passes_feedback(monkeypatch):
    """쉬운 질문은 소형 모델, 어려운 질문은 큰 모델 — 검증 지적 · 분석 숫자는 프롬프트에 그대로 들어가야 반영된다."""
    st = get_settings()
    monkeypatch.setattr(st, "small_llm_model", "fake-small")
    monkeypatch.setattr(st, "small_llm_base_url", "http://small/v1")
    seen = []
    monkeypatch.setattr(llm, "chat", lambda cfg, system, user, **kw: seen.append((cfg, user)) or {"text": "답 [1].", "usage": {}})
    easy = writer.write("배수 필터 위치", [_src(1, AS_TEXT)], None, LCFG)
    assert easy["level"] == "easy" and easy["model"] == "fake-small" and seen[-1][0].base_url == "http://small/v1"
    assert [u["chunk_id"] for u in easy["used"]] == [1]
    hard = writer.write("왜 배수가 안 되고 어떻게 고치는지 비교해 설명해 주세요", [_src(1, AS_TEXT)],
                        {"ok": True, "result": "합계 30"}, LCFG, feedback="근거 없는 문장: X", previous="앞 답")  # fmt: skip
    assert hard["level"] == "hard" and hard["model"] == "fake-big"
    user = seen[-1][1]
    assert "합계 30" in user and "근거 없는 문장: X" in user and "앞 답" in user

    monkeypatch.setattr(st, "small_llm_model", None)  # 소형 모델이 없으면 모두 기본 모델
    assert writer.write("배수 필터 위치", [_src(1, AS_TEXT)], None, LCFG)["model"] == "fake-big"


# ── MA7 검증 ────────────────────────────────────────────────────────────────
def test_critic_pass_revise_reject():
    srcs = [_src(1, AS_TEXT)]
    ok = critic.review("배수가 안 될 때", "배수 필터를 청소하세요 [1].", srcs, None)
    assert ok["decision"] == "pass" and not ok["issues"]

    bad = critic.review("배수가 안 될 때", "전혀 다른 이야기를 지어냈습니다 [1]. 없는 번호입니다 [7].", srcs, None)
    assert bad["decision"] == "revise"
    assert any("근거 일치" in i for i in bad["issues"]) and any("없는 근거 번호" in i for i in bad["issues"])

    # 분석 결과 숫자를 답에 쓰지 않았으면(다른 숫자를 지어냄) 고쳐 쓰게
    num = critic.review("합계", "배수 필터를 청소하세요 [1].", srcs, {"ok": True, "result": "합계 42"})
    assert num["decision"] == "revise" and any("42" in i for i in num["issues"])

    # 규정 위반은 고쳐 쓰게 두지 않고 반려 — 위험한 자가 조치(고객 AS)
    rej = critic.review("배수", "직접 분해해서 교체하세요 [1].", srcs, None, domain="support")
    assert rej["decision"] == "reject" and rej["policy"] == "block"


def test_critic_passes_refusal():
    # 근거가 부족해 거절한 답은 '근거 없는 문장'으로 되돌리지 않는다 — 고쳐 쓰라 하면 지어내게 만든다
    from app.stages.rag.answer import NOT_FOUND

    r = critic.review("보증금 반환", f"{NOT_FOUND}.", [_src(1, AS_TEXT)], None)
    assert r["decision"] == "pass"


# ── MA8 출력 ────────────────────────────────────────────────────────────────
def test_output_compose_without_tts(monkeypatch):
    monkeypatch.setattr(get_settings(), "tts_url", None)
    monkeypatch.setattr(output.httpx, "post", lambda *a, **k: pytest.fail("TTS 가 꺼져 있으면 부르지 않는다"))
    srcs = [_src(i, "t", media={"url": f"/m/{i}"}) for i in range(6)] + [_src(9, "글")]
    out = output.compose("답 [1].", {"chart": {"labels": ["a"], "values": [1]}}, srcs, tts=True)
    assert out["audio"] is None and not out["tts_available"] and out["chart"] == {"labels": ["a"], "values": [1]}
    assert [i["n"] for i in out["images"]] == [1, 2, 3, 4]  # 그림은 4장까지
    assert output.compose("답", None, [], tts=False)["chart"] is None


def test_output_speak_strips_citations(monkeypatch):
    """근거 번호 [1, 2] 를 소리로 읽으면 듣는 사람에게 잡음이다 — 합성 요청에서 뺀다."""
    monkeypatch.setattr(get_settings(), "tts_url", "http://tts/v1/")
    sent = {}

    def post(url, json, timeout):
        sent.update(url=url, input=json["input"])
        return httpx.Response(200, content=b"ID3mp3", request=httpx.Request("POST", url))

    monkeypatch.setattr(output.httpx, "post", post)
    a = output.speak("필터를 청소하세요 [1, 2]. 끝 [3].")
    assert sent["url"] == "http://tts/v1/audio/speech" and "[" not in sent["input"]
    assert a["bytes"] == 6 and (output.audio_dir() / a["name"]).read_bytes() == b"ID3mp3"

    def fail(*a, **k):
        raise httpx.ConnectError("꺼짐")

    monkeypatch.setattr(output.httpx, "post", fail)
    assert "음성 합성 실패" in output.speak("x")["error"]  # 음성이 실패해도 글 답은 그대로 나간다
