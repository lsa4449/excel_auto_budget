from datetime import datetime

import pytest

from app.categorize import categorize
from app.parser import parse_message

NOW = datetime(2026, 11, 10, 20, 0)

# 카드사별 대표 형식 (이름·카드번호는 가상의 예시)
CASES = [
    ("[Web발신]\n신한카드(1234)승인 홍*동 12,500원(일시불)11/10 12:34 스타벅스강남점 누적1,234,567원",
     "신한", 12500, False, "스타벅스강남점", "2026-11-10T12:34"),
    ("[Web발신]\n삼성카드 승인 홍*동\n38,000원 일시불\n11/09 19:02 배달의민족\n누적 512,300원",
     "삼성", 38000, False, "배달의민족", "2026-11-09T19:02"),
    ("[Web발신]\nKB국민카드1234승인\n홍*동님\n6,900원 일시불\n11/08 08:11\nGS25역삼점\n누적 98,000원",
     "KB국민", 6900, False, "GS25역삼점", "2026-11-08T08:11"),
    ("[Web발신]\n현대카드 M 승인\n홍*동\n129,000원 3개월\n11/07 15:40\n쿠팡\n누적 1,002,000원",
     "현대", 129000, False, "쿠팡", "2026-11-07T15:40"),
    ("[Web발신]\n롯데카드 승인취소 홍*동 12,500원 11/10 13:00 스타벅스강남점",
     "롯데", 12500, True, "스타벅스강남점", "2026-11-10T13:00"),
    ("[Web발신]\n우리카드(5678)체크승인 홍*동님 4,500원 11/06 09:30 메가MGC커피 잔액 302,100원",
     "우리", 4500, False, "메가MGC커피", "2026-11-06T09:30"),
    ("[Web발신]\nNH카드1*2*승인 홍*동 17,000원 일시불 11/05 21:15 카카오T택시",
     "NH농협", 17000, False, "카카오T택시", "2026-11-05T21:15"),
]


@pytest.mark.parametrize("text,card,amount,cancel,merchant,paid", CASES)
def test_sms_formats(text, card, amount, cancel, merchant, paid):
    p = parse_message(text, now=NOW)
    assert p is not None
    assert p.card == card
    assert p.amount == amount
    assert p.is_cancel is cancel
    assert p.merchant == merchant
    assert p.paid_at.isoformat(timespec="minutes") == paid


def test_push_without_datetime_uses_app_name_hint():
    p = parse_message("결제 승인 15,000원\n올리브영 강남본점", sender_hint="com.shcard.smartpay", now=NOW)
    assert p.card == "신한"
    assert p.amount == 15000
    assert p.paid_at is None
    assert p.merchant == "올리브영 강남본점"


@pytest.mark.parametrize("text", [
    "[Web발신]\n(광고) 신한카드 11월 이벤트! 최대 50,000원 캐시백",
    "[Web발신]\n삼성카드 결제대금 출금 예정 안내",
    "[Web발신]\n(광고) 삼성카드 결제 시 5,000원 할인 쿠폰 증정",
    "[Web발신]\n현대카드 11월 결제예정금액 512,300원 (11/25 출금)",
    "인증번호 [123456]을 입력하세요",
    "[Web발신]\n신한카드 승인거절 12,500원 한도초과",
])
def test_non_payment_ignored(text):
    assert parse_message(text, now=NOW) is None


def test_year_rollover():
    p = parse_message("신한카드 승인 10,000원 12/31 23:50 CU", now=datetime(2027, 1, 1, 0, 5))
    assert p.paid_at.year == 2026


@pytest.mark.parametrize("merchant,cat", [
    ("스타벅스강남점", "카페/디저트"),
    ("배달의민족", "배달"),
    ("GS25역삼점", "편의점"),
    ("쿠팡", "쇼핑"),
    ("카카오T택시", "교통"),
    ("NETFLIX.COM", "구독"),
    ("동네세탁소", "기타"),
])
def test_categorize(merchant, cat):
    assert categorize(merchant) == cat
