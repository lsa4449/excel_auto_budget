"""가맹점명 → 카테고리 자동 분류, 카테고리별 '절약 가능률'.

절약 가능률 = 그 카테고리 지출 중 노력하면 줄일 수 있다고 보는 비율(추정치).
rules.json 을 만들면 기본값을 덮어쓸 수 있다 (rules.example.json 참고).
"""
from __future__ import annotations

import json
from functools import lru_cache

from . import config

DEFAULT_KEYWORDS: dict[str, list[str]] = {
    "카페/디저트": ["스타벅스", "투썸", "이디야", "메가", "컴포즈", "빽다방", "폴바셋", "할리스", "커피", "카페",
                 "파리바게뜨", "뚜레쥬르", "베이커리", "배스킨", "설빙", "공차"],
    "배달": ["배달의민족", "배민", "우아한형제들", "요기요", "쿠팡이츠", "땡겨요"],
    "편의점": ["GS25", "지에스25", "CU", "씨유", "세븐일레븐", "이마트24", "미니스톱", "편의점"],
    "식비": ["식당", "김밥", "국밥", "치킨", "피자", "버거", "맥도날드", "롯데리아", "버거킹", "맘스터치", "서브웨이",
           "한솥", "본죽", "분식", "마라", "초밥", "고기", "식육", "푸드", "키친", "반점", "도시락"],
    "장보기": ["이마트", "홈플러스", "롯데마트", "코스트코", "트레이더스", "농협하나로", "하나로마트", "마트",
            "컬리", "오아시스", "SSG"],
    "술/유흥": ["주점", "포차", "호프", "이자카야", "와인", "BAR", "바 ", "노래", "PC방", "피씨방"],
    "교통": ["택시", "카카오T", "카카오모빌리티", "티머니", "버스", "지하철", "코레일", "KTX", "SRT", "주유", "GS칼텍스",
           "SK에너지", "S-OIL", "현대오일", "주차", "하이패스", "타다", "쏘카", "그린카"],
    "쇼핑": ["쿠팡", "11번가", "G마켓", "옥션", "무신사", "29CM", "지그재그", "에이블리", "올리브영", "다이소",
           "네이버페이", "NAVER", "위메프", "티몬", "알리", "테무", "유니클로", "자라", "H&M"],
    "구독": ["넷플릭스", "NETFLIX", "유튜브", "YOUTUBE", "GOOGLE", "구글", "APPLE", "애플", "멜론", "지니",
           "스포티파이", "SPOTIFY", "티빙", "웨이브", "왓챠", "쿠팡와우", "디즈니", "CHATGPT", "OPENAI",
           "ANTHROPIC", "CLAUDE", "노션", "NOTION"],
    "통신": ["SKT", "에스케이텔레콤", "KT", "LG유플러스", "U+", "알뜰폰"],
    "의료/건강": ["병원", "의원", "약국", "치과", "한의원", "피트니스", "헬스", "필라테스"],
    "문화/여가": ["CGV", "메가박스", "롯데시네마", "교보문고", "영풍문고", "예스24", "알라딘", "인터파크", "티켓",
              "야놀자", "여기어때", "에어비앤비", "숙박", "호텔"],
    "교육": ["학원", "인프런", "클래스101", "패스트캠퍼스", "멀티캠퍼스", "유데미", "UDEMY"],
}

# 카테고리별 절약 가능률(0~1). 필수 지출일수록 낮게.
DEFAULT_SAVING_RATES: dict[str, float] = {
    "카페/디저트": 0.5,
    "배달": 0.5,
    "술/유흥": 0.5,
    "편의점": 0.4,
    "쇼핑": 0.3,
    "구독": 0.3,
    "문화/여가": 0.2,
    "식비": 0.15,
    "장보기": 0.1,
    "교통": 0.1,
    "통신": 0.1,
    "교육": 0.0,
    "의료/건강": 0.0,
    "기타": 0.2,
}

CATEGORY_ORDER = list(DEFAULT_SAVING_RATES.keys())


@lru_cache
def load_rules() -> tuple[dict[str, list[str]], dict[str, float]]:
    keywords = {k: list(v) for k, v in DEFAULT_KEYWORDS.items()}
    rates = dict(DEFAULT_SAVING_RATES)
    path = config.RULES_PATH
    if path.exists():
        user = json.loads(path.read_text(encoding="utf-8"))
        for cat, words in user.get("keywords", {}).items():
            # 사용자 규칙을 앞에 둬서 우선 적용
            keywords[cat] = list(words) + keywords.get(cat, [])
        rates.update(user.get("saving_rates", {}))
    return keywords, rates


def categorize(merchant: str) -> str:
    keywords, _ = load_rules()
    m = merchant.upper()
    for cat, words in keywords.items():
        if any(w.upper() in m for w in words):
            return cat
    return "기타"


def saving_rate(category: str) -> float:
    _, rates = load_rules()
    return float(rates.get(category, rates.get("기타", 0.2)))


def all_categories() -> list[str]:
    keywords, rates = load_rules()
    cats = list(CATEGORY_ORDER)
    for c in list(keywords) + list(rates):
        if c not in cats:
            cats.append(c)
    return cats
