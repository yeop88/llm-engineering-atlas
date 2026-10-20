"""AS2 긴급도 · 오류 코드 규칙, AS4 코드 맞춤 · 시험 그림 — 모델 없이 도는 순수 함수."""

import io

import pytest
from PIL import Image

from app.stages.as_service import photo, setup, triage


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("콘센트에서 불꽃이 튀었어요", "safety"),
        ("세탁기 만지다가 찌릿했어요", "safety"),
        ("건조기에서 타는 냄새가 나요", "safety"),
        ("가스 냄새가 나는 것 같아요", "safety"),
        ("물이 새고 연기도 나요", "safety"),  # 안전이 높음보다 먼저
        ("바닥으로 물이 새요", "high"),
        ("전원이 안 켜져요", "high"),
        ("E9 이 떴어요", "high"),
        ("세제는 어느 칸에 넣나요?", "normal"),
        ("", "normal"),
    ],
)
def test_urgency_order(text, want):
    assert triage.urgency(text) == want


def test_codes_known_only():
    # '5G' · 'A4' 같은 일반 낱말은 코드가 아니다 — 알려진 오류 코드만 뽑는다
    assert triage.codes("5G 와이파이 쓰고 A4 용지에 적어 뒀는데 E4 가 떠요") == ["E4"]
    assert triage.codes("표시창에 d80 이 나와요") == ["d80"]
    assert triage.codes("UE 랑 E4, 다시 E4") == ["UE", "E4"]  # 중복 없이 나온 순서대로
    assert triage.codes("오류 없이 그냥 소리가 커요") == []
    assert triage.codes("WE4 같은 낱말 안의 글자") == []  # 앞뒤가 영숫자면 코드가 아님


def test_snap():
    known = ["E4", "OE", "D80", "UE"]
    assert photo.snap("e4", known) == ("E4", False)  # 대소문자 · 공백만 다르면 그대로
    assert photo.snap(" E 4 ", known) == ("E4", False)
    assert photo.snap("0E", known) == ("OE", True)  # 비슷한 글자 O↔0
    assert photo.snap("DB0", known) == ("D80", True)  # B↔8
    assert photo.snap("F7", known) == ("F7", False)  # 모르는 코드는 고치지 않는다


def test_make_test_image_is_jpeg():
    for hard in (False, True):
        b = photo.make_test_image("E4", seed=3, hard=hard)
        assert b[:3] == b"\xff\xd8\xff"
        im = Image.open(io.BytesIO(b))
        assert im.format == "JPEG" and im.size == (640, 480)
    assert photo.make_test_image("E4", seed=1) == photo.make_test_image("E4", seed=1)  # 같은 seed 면 같은 그림


def test_preset_shape():
    p = triage.preset()
    assert {"고장", "사용법"} <= set(p["intents"])
    assert len(p["inquiries"]) >= 40 and all(q["intent"] in p["intents"] for q in p["inquiries"])
    # 라벨의 긴급도와 규칙이 같아야 분류 평가의 '안전 재현율'이 의미가 있다
    safety = [q for q in p["inquiries"] if q["urgency"] == "safety"]
    assert safety and all(triage.urgency(q["text"]) == "safety" for q in safety)
    assert setup.known_codes() == sorted(set(setup.known_codes()))


@pytest.mark.parametrize(
    ("reply", "code", "snapped"),
    [
        ('{"code": "0E", "display": "0E", "seen": true}', "OE", True),
        ('{"code": "", "display": "E4", "seen": true}', "E4", False),  # 코드 칸을 비우고 표시창 글자에만 적은 경우
        ('{"code": "", "display": "START 0E", "seen": true}', "OE", True),
        ('{"code": "", "display": "MENU", "seen": true}', "", False),  # 알려진 코드가 아닌 글자는 코드로 보지 않는다
        ("배수 필터를 청소하세요 [1].", "", False),
        ("모르겠어요", "", False),
    ],
)
def test_read_code(monkeypatch, reply, code, snapped):
    # 목록 조각([1])이나 JSON 이 아닌 답은 '읽지 못함'으로 — 오류로 상담 전체가 멈추지 않게
    monkeypatch.setattr(photo.llm, "chat", lambda *a, **k: {"text": reply, "seconds": 0.1})
    r = photo.read_code(None, b"jpg", ["OE", "E4"])
    assert (r["code"], r["snapped"], r["seen"]) == (code, snapped, bool(code))
