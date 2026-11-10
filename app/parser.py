"""카드 결제 문자/푸시 알림 파서.

국내 카드사 알림은 형식이 조금씩 다르지만 대부분 아래 요소를 포함한다.
  - 카드사 이름 (신한, 삼성, KB국민, 현대, 롯데, 우리, 하나, BC, NH농협 ...)
  - 승인 / 취소 여부
  - 금액 "12,500원"
  - 일시 "11/10 12:34"
  - 가맹점명 (일시 뒤 또는 다음 줄)
  - 누적/잔여 한도 금액 (무시해야 함)

정규식 하나로 모든 형식을 맞추기보다는 "요소별로 찾아내는" 방식을 쓴다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

CARD_COMPANIES = [
    ("KB국민", ["KB국민", "국민카드", "KB카드", "KB Pay", "KB"]),
    ("신한", ["신한"]),
    ("삼성", ["삼성"]),
    ("현대", ["현대카드", "현대"]),
    ("롯데", ["롯데"]),
    ("우리", ["우리카드", "우리"]),
    ("하나", ["하나카드", "하나"]),
    ("NH농협", ["NH", "농협"]),
    ("BC", ["BC", "비씨"]),
    ("IBK기업", ["IBK", "기업"]),
    ("카카오뱅크", ["카카오뱅크"]),
    ("토스뱅크", ["토스뱅크", "토스"]),
    ("씨티", ["씨티"]),
]

# 결제 알림이 아닌 것(광고·안내·출금 등)을 거르기 위한 키워드
APPROVAL_WORDS = ("승인", "결제", "사용", "일시불", "할부")
CANCEL_WORDS = ("취소", "승인취소")
# 결제 알림처럼 보이지만 실제 지출이 아닌 것
NOT_PAYMENT_WORDS = ("거절", "(광고)", "[광고]", "결제예정", "결제대금", "청구", "출금예정", "이벤트", "인증번호")
IGNORE_LINE_WORDS = ("누적", "잔액", "잔여", "한도", "포인트", "Web발신", "web발신", "국외발신", "국제발신")

AMOUNT_RE = re.compile(r"(?<![\d,])(\d{1,3}(?:,\d{3})+|\d+)\s*원")
DATETIME_RE = re.compile(r"(\d{1,2})[/.-](\d{1,2})\s+(\d{1,2}):(\d{2})")
INSTALLMENT_RE = re.compile(r"(일시불|\d{1,2}\s*개월)")
MASKED_NAME_RE = re.compile(r"[가-힣A-Za-z]\*[가-힣A-Za-z]*\s*님?")


@dataclass
class ParsedPayment:
    card: str
    amount: int
    is_cancel: bool
    paid_at: Optional[datetime]
    merchant: str
    installment: str
    card_last4: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["paid_at"] = self.paid_at.isoformat(timespec="minutes") if self.paid_at else None
        return d


def _clean(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"\[(?:Web|web|국외|국제)발신\]", "\n", text)
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


APP_PACKAGE_HINTS = {
    "shcard": "신한", "samsungcard": "삼성", "kbcard": "KB국민", "hyundaicard": "현대",
    "lottecard": "롯데", "lcac": "롯데", "wooricard": "우리", "hanaskcard": "하나", "hanacard": "하나",
    "nhallonepay": "NH농협", "nhcard": "NH농협", "bccard": "BC", "paybook": "BC",
}


def _detect_card(text: str, hint: str = "") -> str:
    low_hint = hint.lower()
    for key, name in APP_PACKAGE_HINTS.items():
        if key in low_hint:
            return name
    # 앱 이름/발신자 → 앞쪽 두 줄 → 전체 순서로 찾는다 (가맹점명에 섞인 단어 오인 방지)
    head = "\n".join(text.split("\n")[:2])
    for hay in (hint, head, text):
        if not hay:
            continue
        for name, keys in CARD_COMPANIES:
            if any(k in hay for k in keys):
                return name
    return "기타"


def _find_amount(text: str) -> Optional[int]:
    """누적/잔액 금액이 아닌 첫 번째 '...원' 금액."""
    for line in text.split("\n"):
        for m in AMOUNT_RE.finditer(line):
            before = line[max(0, m.start() - 6): m.start()]
            if any(w in before for w in ("누적", "잔액", "잔여", "한도")):
                continue
            return int(m.group(1).replace(",", ""))
    return None


def _find_datetime(text: str, now: datetime) -> tuple[Optional[datetime], Optional[re.Match]]:
    m = DATETIME_RE.search(text)
    if not m:
        return None, None
    month, day, hour, minute = map(int, m.groups())
    year = now.year
    # 1월에 12월 결제 알림이 오는 경우
    if month > now.month + 1:
        year -= 1
    try:
        return datetime(year, month, day, hour, minute), m
    except ValueError:
        return None, None


def _strip_noise(s: str) -> str:
    s = AMOUNT_RE.sub(" ", s)
    s = INSTALLMENT_RE.sub(" ", s)
    s = MASKED_NAME_RE.sub(" ", s)
    s = re.sub(r"(승인취소|승인|취소|결제|체크|신용)", " ", s)
    s = re.sub(r"[\(\)\[\]]", " ", s)
    return re.sub(r"\s+", " ", s).strip(" -·:")


def _find_merchant(text: str, dt_match: Optional[re.Match], card: str) -> str:
    lines = text.split("\n")
    # 1) 일시와 같은 줄, 일시 뒤에 붙은 텍스트 (신한/삼성형: "11/10 12:34 스타벅스")
    if dt_match:
        for i, line in enumerate(lines):
            m = DATETIME_RE.search(line)
            if not m:
                continue
            after = _strip_noise(line[m.end():])
            after = re.split(r"누적|잔액|잔여", after)[0].strip()
            if after:
                return after
            # 2) 일시 다음 줄 (KB/현대형)
            for nxt in lines[i + 1:]:
                if any(w in nxt for w in IGNORE_LINE_WORDS):
                    continue
                cand = _strip_noise(nxt)
                if cand:
                    return cand
            break
    # 3) 일시가 없는 푸시 알림: 카드사·금액·누적이 아닌 마지막 줄
    for line in reversed(lines):
        if any(w in line for w in IGNORE_LINE_WORDS):
            continue
        cand = _strip_noise(line)
        if cand and card not in cand and "카드" not in cand:
            return cand
    return "알수없음"


def parse_message(text: str, sender_hint: str = "", now: Optional[datetime] = None) -> Optional[ParsedPayment]:
    """결제 알림이면 ParsedPayment, 아니면 None."""
    now = now or datetime.now()
    if not text:
        return None
    body = _clean(text)
    is_cancel = any(w in body for w in CANCEL_WORDS)
    if not is_cancel and not any(w in body for w in APPROVAL_WORDS):
        return None
    if any(w in body for w in NOT_PAYMENT_WORDS):
        return None

    amount = _find_amount(body)
    if not amount:
        return None

    card = _detect_card(body, sender_hint)
    paid_at, dt_match = _find_datetime(body, now)
    merchant = _find_merchant(body, dt_match, card)
    inst = INSTALLMENT_RE.search(body)
    last4 = ""
    m4 = re.search(r"[\(\[]?(\d{4})[\)\]]?\s*(?:승인|취소)", body) or re.search(r"[\(\[](\d{4})[\)\]]", body)
    if m4:
        last4 = m4.group(1)

    return ParsedPayment(
        card=card,
        amount=amount,
        is_cancel=is_cancel,
        paid_at=paid_at,
        merchant=merchant[:60],
        installment=inst.group(1).replace(" ", "") if inst else "",
        card_last4=last4,
    )
