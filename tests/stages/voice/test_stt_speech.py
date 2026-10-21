"""VC1 음성 인식 후처리(용어 복원 · 정확도) · VC4 합성용 읽기 규칙. 인식기(Whisper)는 부르지 않는다 — transcribe 를 바꿔 끼운다."""

import numpy as np
import pytest

from app.core.config import get_settings
from app.stages.voice import speech, stt

VOCAB = ["WM-200", "E4", "OE"]


# ── stt ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("s", "n"), [("이백", 200), ("삼십오", 35), ("이공공", 200), ("십", 10), ("백이십삼", 123), ("", None), ("가", None)]
)
def test_sino_number(s, n):
    # 고객은 같은 번호를 자릿값('이백')으로도 한 자리씩('이공공')으로도 읽는다 — 둘 다 같은 숫자여야 모델명이 복원된다
    assert stt.sino_number(s) == n


def test_spellings_cover_both_readings():
    assert stt._spellings("E4") == ["이사", "이 사"]
    sp = stt._spellings("WM-200")
    assert {"더블유엠이백", "더블유엠 이백", "더블유엠 이 공 공", "더블유엠이공공"} <= set(sp)
    assert stt._spellings("OE") == ["오이"] and stt._spellings("한글") == []


def test_restore_terms_in_code_context_only():
    """짧은 코드(E4 · OE)는 소리가 흔한 낱말과 같다 — '이사 가요' 를 'E4 가요' 로 바꾸면 고객 말이 망가진다.
    그래서 코드를 말하는 문맥(뜨다 · 오류 · 표시)일 때만 바꾸고, 긴 모델명은 문맥 없이도 바꾼다."""
    assert stt.restore_terms("다음 주에 이사 가요", VOCAB) == ("다음 주에 이사 가요", [])
    assert stt.restore_terms("이사가 떠요", VOCAB) == ("E4가 떠요", [{"from": "이사", "to": "E4"}])
    assert stt.restore_terms("표시창에 오이 나와요", VOCAB)[0] == "표시창에 OE 나와요"
    assert stt.restore_terms("더블유엠 이백 모델이에요", VOCAB)[0] == "WM-200 모델이에요"
    assert stt.restore_terms("더블유엠 이 공 공 인데 이사 떠요", VOCAB)[0] == "WM-200 인데 E4 떠요"
    # '이다' 활용이 붙은 말도 복원(고친 버그: 'WM-200인데요' · 'WM-200입니다' 가 소리 그대로 남았다)
    assert stt.restore_terms("더블유엠 이백인데요", VOCAB)[0] == "WM-200인데요"
    assert stt.restore_terms("더블유엠이백입니다", VOCAB)[0] == "WM-200입니다"
    # 낱말 안('이사하다가')은 문맥이 있어도 그대로
    assert stt.restore_terms("이사하다가 오류가 났어요", VOCAB)[0] == "이사하다가 오류가 났어요"


def test_vocab_prompt():
    assert stt.vocab_prompt([]) == ""
    p = stt.vocab_prompt(VOCAB)
    assert p.startswith("가전 AS 상담 통화") and "WM-200, E4, OE" in p
    assert stt.vocab_prompt([f"T{i}" for i in range(50)], limit=3).count(",") == 2


def test_cer_and_term_hits():
    # 띄어쓰기 · 문장부호 차이는 오류가 아니다(한국어 띄어쓰기는 사람마다 다름)
    assert stt.cer("세탁기 물이 안 빠져요.", "세탁기물이 안빠져요") == 0.0
    assert stt.cer("세탁기 E4", "세탁기 이사") == pytest.approx(0.4)
    assert stt.cer("", "") == 0.0 and stt.cer("", "가") == 1.0
    # 용어 정확도: 오류 코드 하나가 틀리면 검색 전체가 틀린다 — 글자 오류율과 따로 센다
    assert stt.term_hits("WM-200 에 E4", "WM200 에 이사", VOCAB) == (1, 2)


def test_engine_choice(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "voice_stt_engine", "auto")
    monkeypatch.setattr(s, "stt_url", None)
    assert stt.default_engine() == "local" and stt.engines()["openai"] is False
    monkeypatch.setattr(s, "stt_url", "http://stt.local/v1")
    assert stt.default_engine() == "openai"
    monkeypatch.setattr(s, "voice_stt_engine", "local")
    assert stt.default_engine() == "local"
    with pytest.raises(ValueError):
        stt.transcribe(np.zeros(16000, dtype=np.float32), "모름")
    monkeypatch.setattr(s, "stt_url", None)
    with pytest.raises(ValueError, match="STT_URL"):
        stt.transcribe(np.zeros(16000, dtype=np.float32), "openai")


def test_evaluate_variants_with_fake_engine(monkeypatch):
    """세 갈래(사전 없음 · 앞 문맥 · 앞 문맥 + 복원)를 같은 소리로 비교 — 사전이 어디서 효과가 나는지 나눠 보려고."""
    calls = []

    def fake(x, engine=None, prompt=""):
        calls.append((engine, prompt))
        if engine == "openai":
            raise ValueError("STT_URL 이 설정되지 않았습니다")
        text = "WM-200 에 이사가 떠요" if prompt else "더블유엠 이백에 이사가 떠요"
        return {"text": text, "engine": engine, "seconds": 0.1, "rtf": 0.1}

    monkeypatch.setattr(stt, "transcribe", fake)
    items = [{"id": "a.wav", "ref": "WM-200 에 E4 가 떠요", "audio": np.zeros(16000, dtype=np.float32)}]
    res = stt.evaluate(items, ["local", "openai"], VOCAB)
    by = {(r["engine"], r["variant"]): r for r in res["results"]}
    assert by[("local", "plain")]["term_acc"] == 0.0
    assert by[("local", "prompt")]["term_acc"] == 0.5  # 앞 문맥으로 모델명은 표기대로, 짧은 코드는 여전히 소리대로
    best = by[("local", "prompt+restore")]
    assert best["term_acc"] == 1.0 and best["cer"] < by[("local", "plain")]["cer"] and best["rtf"] == 0.1
    assert best["rows"][0]["hyp"] == "WM-200 에 E4가 떠요"
    # 엔진 하나가 실패해도 평가 전체가 멈추지 않고 그 엔진만 오류로 남는다
    assert {r["status"] for r in res["results"] if r["engine"] == "openai"} == {"error"}
    assert any(p for _, p in calls) and res["n"] == 1
    assert [r["variant"] for r in stt.evaluate(items, ["local"], [])["results"]] == ["plain"]  # 사전이 없으면 한 갈래


# ── speech ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("E4 가 떠요", "이 사 가 떠요"),  # 코드는 한 글자씩
        ("WM-200 모델입니다", "더블유엠 이백 모델입니다"),  # 모델 번호는 자릿값
        ("DR300 건조기", "디알 삼백 건조기"),
        ("OE 오류", "오 이 오류"),
        ("고객센터 010-1234-5678", "고객센터 공 일 공, 일 이 삼 사, 오 육 칠 팔"),  # 전화번호는 한 자리씩
        ("온도는 60℃, 무게 7.5kg", "온도는 육십 도, 무게 칠 점 오 킬로그램"),
        ("1. 전원을 끄세요\n2. 필터를 빼세요", "첫 번째, 전원을 끄세요\n두 번째, 필터를 빼세요"),  # '일 번째' 가 아님
        ("필터를 청소하세요 [1, 2].", "필터를 청소하세요."),  # 근거 번호는 읽지 않는다
        ("**굵게** 표시", "굵게 표시"),
    ],
)
def test_spoken_reading_rules(text, spoken):
    assert speech.spoken(text) == spoken


def test_sino_and_ordinal():
    assert speech.sino(0) == "영" and speech.sino(115) == "백십오" and speech.sino(20000) == "이만"
    assert speech._ordinal(3) == "세 번째" and speech._ordinal(12) == "십이 번"


def test_sentences_streaming_split():
    done, rest = speech.sentences("첫 문장입니다. 두 번째 문장이에요 그리고 세")
    # 마침표는 문장 글에 남아야 한다(고친 버그: 경계가 마침표를 삼켜 답 글에서 빠졌다)
    assert done == ["첫 문장입니다.", "두 번째 문장이에요"] and rest == "그리고 세"
    assert speech.sentences("남은 조각", final=True) == (["남은 조각"], "")
    # 낱말 '다' 뒤에서는 끊지 않는다(고친 버그: '물이 다' 만 먼저 읽혔다)
    assert speech.sentences("물이 다 빠지면 문이 열립니다.", final=True)[0] == ["물이 다 빠지면 문이 열립니다."]


def test_long_sentence_split_at_comma():
    # 합성 한 번이 길면 첫 소리가 늦다 — 긴 문장은 쉼표에서 한 번 더 끊는다
    s = "가나다라마바사아자차카타파하 가나다라마바사, 아자차카타파하 가나다라마바사아자차카타, 파하 가나다라 끝입니다."
    out, _ = speech.sentences(s, final=True, max_chars=40)
    assert len(out) == 2 and out[0].endswith(",") and "".join(out).replace(" ", "") == s.replace(" ", "")
    # 끝나지 않은 아주 긴 조각도 마지막 쉼표까지는 먼저 내보낸다
    long_rest = "가" * 30 + ", " + "나" * 80 + ", 다라"
    done, rest = speech.sentences(long_rest, max_chars=40)
    assert done and done[-1].endswith(",") and rest.strip() == "다라"


def test_synth_without_tts_url(monkeypatch):
    # TTS 서버가 없으면 None — 화면이 브라우저 음성으로 같은 '읽는 글'을 읽는다
    monkeypatch.setattr(get_settings(), "tts_url", None)
    assert speech.synth("안녕하세요") is None
    monkeypatch.setattr(get_settings(), "tts_url", "http://tts.local/v1")
    assert speech.synth("   ") is None
