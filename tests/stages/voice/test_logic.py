"""VC3 지연 예산 · 문장 흘려보내기, VC5 감정 · 이관, VC6 상담원 보조, VC7 요약 검증. LLM 은 부르지 않는다(가짜 조각 · 바꿔 끼운 chat_json)."""

import pytest

from app.core import llm
from app.stages.voice import assist, emotion, fastrag, summary


# ── VC3 fastrag ──────────────────────────────────────────────────────────────
def test_budget_shares_sum_to_total():
    b = fastrag.budget(1200)
    assert sum(b.values()) == 1200 and b["endpoint"] == 408 and set(b) == set(fastrag.LABELS)
    assert sum(fastrag.budget(2000).values()) == pytest.approx(2000, abs=2)  # 설정을 바꾸면 비율대로


class Clock:
    """가짜 시계 — 부를 때마다 10ms 씩 흐른다. 실제 시간에 기대면 지연 계산을 확인할 수 없다."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.01
        return self.t


def test_stream_emits_sentences_as_they_complete():
    deltas = iter(
        [{"delta": "필터를 청소하세요"}, {"delta": " [1]. 고객님 번호 010-"}, {"delta": "1234-5678 로 연락드릴게요."},
         {"done": True, "text": "전체", "usage": {"output_tokens": 9}, "seconds": 0.5}]
    )  # fmt: skip
    synth_calls = []
    clock = Clock()
    evs = list(fastrag.stream(deltas, 0.0, synth=lambda s: synth_calls.append(s) or "a.mp3", clock=clock,
                              mask=lambda s: s.replace("010-1234-5678", "[전화번호]")))  # fmt: skip
    sents = [e for e in evs if e["type"] == "sentence"]
    # 첫 문장은 두 번째 조각이 오자마자(답 전체를 기다리지 않고) 나온다
    assert [s["n"] for s in sents] == [0, 1] and sents[0]["text"] == "필터를 청소하세요 [1]."
    assert sents[0]["spoken"] == "필터를 청소하세요." and sents[0]["audio"] == "a.mp3"
    # 개인정보는 읽기 전에 가린다 — 소리로 나간 번호는 되돌릴 수 없다
    assert "010" not in sents[1]["text"] and "[전화번호]" in sents[1]["text"] and not any("공 일 공" in c for c in synth_calls)
    assert all(s["ready_ms"] >= s["gen_ms"] for s in sents) and sents[1]["gen_ms"] > sents[0]["gen_ms"]
    done = evs[-1]
    assert done["type"] == "llm_done" and done["text"] == "전체" and done["first_token_ms"] == 10 and done["usage"]["output_tokens"] == 9


def test_stream_without_done_and_synth():
    evs = list(fastrag.stream(iter([{"delta": "남은 말"}]), 0.0, clock=Clock()))
    assert [e["type"] for e in evs] == ["sentence", "llm_done"] and evs[0]["audio"] is None and evs[1]["text"] == ""


def test_report_marks_over_budget_stage():
    rep = fastrag.report({"endpoint": 400, "stt": 500, "retrieve": 50, "first_sentence": None, "tts": 100}, 1200)
    over = {r["stage"]: r["over"] for r in rep["stages"]}
    assert over["stt"] and not over["endpoint"] and not over["first_sentence"]
    assert rep["first_audio_ms"] == 1050 and rep["within"] and rep["worst"]["stage"] == "stt"  # 어느 단계를 고칠지
    agg = fastrag.aggregate([rep, fastrag.report({"endpoint": 1000, "stt": 300}, 1200)])
    assert agg["n"] == 2 and agg["within"] == 0.5 and agg["stages"]["stt"]["over"] == 2 and agg["stages"]["first_sentence"]["n"] == 0
    assert fastrag.aggregate([])["within"] is None


# ── VC5 emotion ──────────────────────────────────────────────────────────────
def test_text_score_cues_are_full_phrases():
    """근거 표시(cues)는 맞은 표현 전체여야 한다 — 고친 버그: 정규식 묶음 때문에 '환불' 이 빈 글로, '왜 자꾸' 가 '자꾸' 로 나왔다."""
    s = emotion.text_score("환불해 주세요")
    assert s["score"] == 0.75 and s["cues"] == ["환불"]  # 강한 표현 하나면 이관 문턱
    m = emotion.text_score("왜 자꾸 안 돼요!!!")
    assert m["cues"] == ["왜 자꾸"] and m["score"] == pytest.approx(0.6)
    assert emotion.text_score("네 알겠습니다 감사합니다")["score"] == 0.0
    assert emotion.text_score("상담원 연결해 주세요")["handoff_request"]


def test_voice_score_is_relative_to_first_utterance():
    base = {"db": -20, "f0": 200, "rate": 5}
    # 원래 목소리가 큰 사람을 화났다고 보지 않게 — 같은 통화 첫 발화 대비 변화만
    assert emotion.voice_score(base, base) == 0.0
    assert emotion.voice_score({"db": -14, "f0": 240, "rate": 6.5}, base) == 1.0
    assert emotion.voice_score({"db": -17, "f0": None, "rate": None}, base) == 0.5
    assert emotion.voice_score(base, None) is None and emotion.voice_score(None, base) is None


def test_assess_escalation_reasons():
    calm = emotion.assess("필터는 어디 있어요", None, None, [])
    assert not calm["escalate"] and calm["tone"] == "calm" and calm["voice"] is None
    assert emotion.assess("상담원 바꿔 주세요", None, None, [])["reasons"] == ["상담원 요청"]
    assert "강한 불만" in emotion.assess("도대체 언제까지 기다려야 돼요", None, None, [])["reasons"]
    # 불만이 두 턴 이어지면 — 한 번의 짜증보다 이어지는 불만이 이관 신호
    two = emotion.assess("아직도 안 돼요 답답하네요!", None, None, [{"text": "다른 말", "emotion": {"score": 0.6}}])
    assert two["score"] >= 0.5 and "불만 두 턴 이어짐" in two["reasons"] and two["tone"] == "apologize"
    # 같은 문제를 세 번
    hist = [{"text": "세탁기 물이 안 빠져요", "emotion": {"score": 0}}, {"text": "세탁기 물이 안 빠져요 진짜", "emotion": {"score": 0}}]
    rep = emotion.assess("세탁기 물이 안 빠져요", None, None, hist)
    assert rep["repeats"] == 3 and "같은 문제 3번" in rep["reasons"]
    assert emotion.assess("연기가 나요", None, None, [], urgent=True)["reasons"] == ["안전 문의"]
    # 목소리 점수가 있으면 섞는다(글 0.65 · 목소리 0.35)
    mix = emotion.assess("필터는 어디 있어요", {"db": -14, "f0": 240, "rate": 6.5}, {"db": -20, "f0": 200, "rate": 5}, [])
    assert mix["voice"] == 1.0 and mix["score"] == 0.35 and mix["tone"] == "care"


def test_emotion_eval_on_preset():
    # 보정에 쓴 라벨 문장 세트(38개)라 높게 나오는 것이 맞다 — 규칙을 바꾸다 이 값이 떨어지면 회귀
    r = emotion.evaluate()
    assert r["n"] == 38 and r["recall"] == 1.0 and r["precision"] >= 0.9 and sum(r["confusion"].values()) == 38
    small = emotion.evaluate([{"text": "환불해 주세요", "escalate": True}, {"text": "감사합니다", "escalate": True}])
    assert small["recall"] == 0.5 and small["precision"] == 1.0 and len(small["errors"]) == 1


# ── VC6 assist ───────────────────────────────────────────────────────────────
def test_assist_questions_from_missing_info():
    vocab = {"models": ["WM-200", "WM-100"], "codes": ["E4"]}
    qs = assist.questions("E9 가 떠요 그대로예요", {}, vocab, "normal", ["E9"])
    assert any("모델명" in q for q in qs) and any("E9" in q for q in qs) and len(qs) == 3
    # 이미 아는 정보는 다시 묻지 않는다
    assert assist.questions("E4 가 떠요", {"product_model": "WM-200"}, vocab, "normal", ["E4"]) == []
    assert assist.questions("타는 냄새", {}, {}, "safety", [])[0].startswith("지금 전원 플러그")


def test_adoption_counts_only_rated():
    sg = [{"intent": "drain", "feedback": "adopted"}, {"intent": "drain", "feedback": "edited"}, {"intent": "noise", "feedback": "ignored"},
          {"intent": "noise", "feedback": None}]  # fmt: skip
    a = assist.adoption(sg)
    # 아무것도 누르지 않은 추천은 '못 본 것'일 수 있어 세지 않는다
    assert a["n"] == 4 and a["rated"] == 3 and a["adopted"] == pytest.approx(0.333, abs=1e-3)
    assert a["by_intent"]["drain"] == {"n": 2, "adopted": 1.0} and a["by_intent"]["noise"]["adopted"] == 0.0
    assert assist.adoption([])["adopted"] is None


# ── VC7 summary ──────────────────────────────────────────────────────────────
TURNS = [
    {"role": "customer", "text": "WM-200 세탁기에서 E4 가 떠요"},
    {"role": "agent", "text": "배수 필터를 청소해 보세요"},
    {"role": "customer", "text": "해 봤는데 그대로예요"},
    {"role": "agent", "text": "10월 3일 오후 2시에 기사님이 방문하겠습니다"},
]


def test_verify_exact_and_overlap_checks():
    ok = summary.verify(
        {"product_model": "WM-200", "codes": ["E4"], "actions": ["배수 필터를 청소"], "promise": "10월 3일 오후 2시 방문"}, TURNS
    )
    assert ok["ok"] and {c["how"] for c in ok["checks"]} == {"표기 일치", "글자 겹침"}
    bad = summary.verify({"product_model": "WM-100", "codes": ["E9"], "diagnosis": "모터 고장입니다"}, TURNS)
    assert not bad["ok"] and bad["n_bad"] == 3


def test_verify_checks_promise_dates():
    """약속의 날짜 · 시각이 전사와 다르면 '확인 필요' — 고친 버그: 묶음 있는 정규식의 findall 이 '10월 3일' 을 빈 글로 돌려 검사가 빠졌다."""
    v = summary.verify({"promise": "10월 4일 오후 2시에 기사님이 방문하겠습니다"}, TURNS)
    date_checks = [c for c in v["checks"] if c["field"] == "promise" and c["how"] == "표기 일치"]
    assert {c["value"] for c in date_checks} >= {"10월 4일", "오후", "2시"}
    assert not v["ok"] and [c["value"] for c in date_checks if not c["ok"]] == ["10월 4일"]


def test_rule_summary():
    s = summary.rule_summary(TURNS, {"product_model": "WM-200"})
    assert s["by"] == "rule" and s["inquiry"] == TURNS[0]["text"] and s["codes"] == ["E4"] and s["product_model"] == "WM-200"
    assert s["actions"] == [TURNS[1]["text"], TURNS[3]["text"]] and summary.transcript_text(TURNS).startswith("고객: WM-200")


def test_summarize_llm_and_failure_fallback(monkeypatch):
    cfg = llm.LLMConfig("openai", "fake")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: ({"inquiry": "E4 문의", "codes": "E4", "actions": ["배수 필터를 청소"],
                                                             "product_model": "", "resolved": False}, {}))  # fmt: skip
    out = summary.summarize(TURNS, {"product_model": "WM-200"}, cfg)
    s = out["summary"]
    assert s["by"] == "llm" and s["codes"] == ["E4"] and s["next"] == []  # 글로 온 목록은 목록으로
    # 통화를 만들 때 받은 모델은 전사에 없어도 맞는 정보 — 비어 있으면 채우고 '통화 정보'로 표시
    assert s["product_model"] == "WM-200" and any(c["how"] == "통화 정보" for c in out["verify"]["checks"])

    def boom(*a, **k):
        raise llm.LLMError("연결 실패")

    monkeypatch.setattr(llm, "chat_json", boom)
    out = summary.summarize(TURNS, {}, cfg)
    assert out["summary"]["by"] == "rule" and "연결 실패" in out["summary"]["llm_error"]
    assert summary.summarize(TURNS, {}, None)["summary"]["by"] == "rule"
