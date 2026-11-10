"""환경 변수(.env) 기반 설정."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name, default))
    return p if p.is_absolute() else BASE_DIR / p


# MacroDroid가 요청 헤더(X-Token)나 ?token= 으로 보내야 하는 비밀 토큰
API_TOKEN = os.getenv("API_TOKEN", "")
DB_PATH = _path("DB_PATH", "data/budget.db")
EXPORT_DIR = _path("EXPORT_DIR", "exports")
# 한 달 예산(원). 0이면 예산 비교 생략
MONTHLY_BUDGET = int(os.getenv("MONTHLY_BUDGET", "0") or 0)
# 사용자 정의 분류 규칙/절약률 파일(선택)
RULES_PATH = _path("RULES_PATH", "rules.json")
# 같은 결제가 문자+푸시로 두 번 들어올 때 중복으로 보는 시간(분)
DEDUP_MINUTES = int(os.getenv("DEDUP_MINUTES", "3"))
