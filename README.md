# 💳 excel_auto_budget — 손으로 안 쓰는 자동 가계부

갤럭시 휴대폰으로 오는 **카드 결제 문자(SMS/LMS/MMS)와 카드사 앱 푸시**를 자동으로 읽어
SQLite에 쌓고, 매달 **지출 요약 · 카테고리별 분석 · 절약 가능 퍼센트**가 들어간 엑셀 파일을 만들어 줍니다.

```
[갤럭시 S25]                         [내 PC / 서버]
 카드 문자 ─┐                        ┌─ FastAPI /webhook
 카드앱 푸시 ┴─▶ MacroDroid ─HTTP POST─▶  ├─ parser.py    문자 → 카드사·금액·일시·가맹점
                                     ├─ categorize.py 가맹점 → 카테고리, 절약률
                                     ├─ SQLite        data/budget.db (중복 제거)
                                     └─ excel.py      exports/2026-11_가계부.xlsx 자동 갱신
```

## 엑셀에 들어가는 것

| 시트 | 내용 |
|---|---|
| **요약** | 총지출, 건수, 예산 사용률, 남은 예산, 일평균, 월말 예상 지출, **절약 가능액 / 절약 가능 퍼센트**, 전월 대비, 절약 포인트 TOP 3 |
| **카테고리별** | 카테고리별 지출·비중·건수, **절약률(직접 수정 가능)**, 절약 가능액, 절약 후 지출 + 원형/막대 차트 |
| **일별** | 날짜별 지출, 누적 지출 vs 예산 페이스 + 차트 |
| **상세내역** | 결제 한 건 = 한 줄. 카테고리 드롭다운으로 바꾸면 다른 시트가 자동 재계산 |
| **월별추이** | 쌓인 모든 달의 총지출과 전월 대비 |

**절약 가능 퍼센트** = Σ(카테고리 지출 × 카테고리 절약률) ÷ 총지출
기본 절약률: 카페·배달·술 50%, 편의점 40%, 쇼핑·구독 30%, 문화 20%, 식비 15%, 장보기·교통·통신 10%, 교육·의료 0%
→ `rules.json` 또는 엑셀 파란 숫자로 내 기준에 맞게 바꿀 수 있습니다.

---

## 1. 서버 설치 (Windows / macOS 공통)

Python 3.10 이상 필요.

```bash
git clone https://github.com/lsa4449/excel_auto_budget.git
cd excel_auto_budget
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # Windows: copy .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(24))"   # 출력값을 .env의 API_TOKEN에 붙여넣기
```

## 2. 서버 실행

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- `http://127.0.0.1:8000/docs` 에서 API를 바로 테스트할 수 있습니다.
- MacroDroid 없이 확인: `python scripts/send_test.py` (1건) / `python scripts/send_test.py --demo` (가상 결제 40건)
- 결제가 들어올 때마다 `exports/YYYY-MM_가계부.xlsx` 가 자동으로 다시 만들어집니다.
- Windows 방화벽이 물어보면 **개인 네트워크 허용**을 선택하세요.

## 3. 휴대폰에서 서버 접속

| 방법 | 장점 | 단점 |
|---|---|---|
| **Tailscale (추천)** | 집 밖 LTE/5G에서도 동작, 포트 개방 불필요, 무료 | PC·폰 둘 다 앱 설치 |
| 같은 Wi-Fi | 설정 없음 (`ipconfig`로 PC IP 확인 → `http://192.168.x.x:8000`) | 집 밖 결제는 누락 |
| 클라우드 VM | 24시간 동작 | 비용·관리, 반드시 HTTPS + 토큰 |

Tailscale: PC와 휴대폰에 설치 → 같은 계정 로그인 → PC의 `100.x.x.x` 주소를 서버 주소로 사용.
PC가 꺼져 있으면 알림을 받을 수 없으니 상시 켜 둔 PC/미니PC/라즈베리파이에 두는 것이 좋습니다.

## 4. MacroDroid 설정

👉 **[docs/macrodroid.md](docs/macrodroid.md)** 에 갤럭시 S25 기준 단계별 설정이 있습니다.
요약하면 매크로 2개:

1. **삼성 메시지 알림**(`승인`/`취소` 포함) → `POST /webhook?token=...&source=sms&title=[not_title]&text=[notification]`
2. **카드사 앱 알림**(`원` 포함) → 같은 요청, `source=push`, `sender=[not_app_name]`

문자와 푸시가 같은 결제를 두 번 알려도 서버가 **중복 제거**합니다
(다른 경로로 같은 카드·같은 금액이 3분 안에 들어오면 하나로 처리).

## 5. API

모든 요청에 헤더 `X-Token: <API_TOKEN>` 또는 `?token=` 필요.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/webhook` | 알림 수신 (JSON·form·쿼리·text 모두 허용). 필드: `text`, `title`, `sender`, `source` |
| GET | `/summary?month=2026-11` | 총지출, 카테고리별, 절약 가능액·퍼센트 |
| GET | `/export?month=2026-11` | 엑셀 다운로드 (휴대폰 브라우저에서 바로 열기 가능) |
| GET | `/transactions?month=` | 거래 목록 |
| POST | `/transactions` | 현금·이체 등 수동 추가 `{"merchant":"시장","amount":8000}` |
| PATCH | `/transactions/{id}` | 카테고리·메모 수정 |
| DELETE | `/transactions/{id}` | 삭제 |
| GET | `/unparsed` | 결제로 인식 못 한 알림 원문 (파서 보완용) |
| GET | `/health` | 서버 상태 |

## 6. 내 카드 형식 맞추기

카드사마다 문자 형식이 조금씩 달라 처음엔 일부가 `/unparsed`에 쌓일 수 있습니다.

1. `/unparsed` 에서 원문 복사 → `tests/test_parser.py` 의 `CASES` 에 기대값과 함께 추가
2. `pytest` 실행 → 실패하면 `app/parser.py` 보완
3. 카테고리가 틀리면 `rules.example.json` → `rules.json` 복사 후 키워드 추가 (서버 재시작)

## 7. 보안·개인정보

- `.env`(토큰), `data/`(DB), `exports/`·`*.xlsx`(지출 내역)는 `.gitignore`로 **Git에 올라가지 않습니다.**
- 토큰 없이는 어떤 API도 호출할 수 없습니다. 인터넷에 직접 공개할 때는 반드시 HTTPS(리버스 프록시 등)를 붙이세요.
- 원문 문자(이름 마스킹·카드 끝자리 포함)는 내 PC의 SQLite에만 저장됩니다.

## 폴더 구조

```
app/
  main.py         FastAPI 엔드포인트
  parser.py       카드 알림 파서
  categorize.py   카테고리 규칙 · 절약률
  db.py           SQLite
  excel.py        월간 엑셀 리포트
  config.py       .env 설정
docs/macrodroid.md  MacroDroid 단계별 설정
scripts/send_test.py 테스트 알림 전송
tests/            pytest
```
