"""서버에 테스트 알림을 보내 MacroDroid 없이 동작을 확인한다.

사용법:
  python scripts/send_test.py                      # 기본 예시 1건 전송
  python scripts/send_test.py --demo               # 이번 달 가상 결제 40건 전송 (엑셀 미리보기용)
  python scripts/send_test.py --url http://192.168.0.10:8000 --text "신한카드 승인 5,000원 ..."
"""
from __future__ import annotations

import argparse
import os
import random
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

SAMPLE = "[Web발신]\n신한카드(1234)승인 홍*동 12,500원(일시불){md} {hm} 스타벅스강남점 누적1,234,567원"
DEMO_MERCHANTS = [
    ("스타벅스강남점", 4500, 7500), ("메가MGC커피", 2000, 4500), ("배달의민족", 18000, 35000),
    ("쿠팡이츠", 15000, 28000), ("GS25역삼점", 2500, 9000), ("CU선릉점", 1800, 7000),
    ("김밥천국", 6000, 9000), ("한솥도시락", 5000, 8000), ("이마트 역삼점", 30000, 90000),
    ("카카오T택시", 6000, 18000), ("쿠팡", 12000, 60000), ("올리브영", 10000, 40000),
    ("NETFLIX.COM", 13500, 13500), ("CGV강남", 15000, 30000), ("이자카야 하루", 30000, 70000),
]
CARDS = ["신한카드(1234)", "삼성카드", "KB국민카드", "현대카드"]


def send(url: str, token: str, text: str, source: str = "sms") -> None:
    r = httpx.post(f"{url}/webhook", headers={"X-Token": token}, data={"text": text, "source": source}, timeout=10)
    print(r.status_code, r.json())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("SERVER_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--token", default=os.getenv("API_TOKEN", ""))
    ap.add_argument("--text")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()

    now = datetime.now()
    if a.demo:
        random.seed(7)
        for _ in range(40):
            name, lo, hi = random.choice(DEMO_MERCHANTS)
            amt = random.randrange(lo, hi + 1, 100) if hi > lo else lo
            day = random.randint(1, now.day)
            text = (f"[Web발신]\n{random.choice(CARDS)} 승인 홍*동 {amt:,}원 일시불 "
                    f"{now.month:02d}/{day:02d} {random.randint(8, 22):02d}:{random.randint(0, 59):02d} {name}")
            send(a.url, a.token, text)
        return
    text = a.text or SAMPLE.format(md=now.strftime("%m/%d"), hm=now.strftime("%H:%M"))
    send(a.url, a.token, text)


if __name__ == "__main__":
    main()
