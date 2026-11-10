import importlib

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("MONTHLY_BUDGET", "1000000")
    monkeypatch.setenv("RULES_PATH", str(tmp_path / "none.json"))
    import app.config, app.categorize, app.db, app.excel, app.main
    for m in (app.config, app.categorize, app.db, app.excel, app.main):
        importlib.reload(m)
    with TestClient(app.main.app) as c:
        yield c


H = {"X-Token": "test-token"}
SMS = "[Web발신]\n신한카드(1234)승인 홍*동 12,500원(일시불)11/10 12:34 스타벅스강남점 누적1,234,567원"


def test_token_required(client):
    assert client.post("/webhook", data={"text": SMS}).status_code == 401


def test_form_webhook_and_dedup(client):
    r = client.post("/webhook", headers=H, data={"text": SMS, "source": "sms"}).json()
    assert r["status"] == "saved" and r["category"] == "카페/디저트"
    # 같은 결제가 카드사 앱 푸시로 한 번 더 들어옴 → 중복 처리
    push = {"title": "신한카드 승인", "text": "12,500원 일시불 11/10 12:35 스타벅스강남점", "source": "push"}
    assert client.post("/webhook", headers=H, data=push).json()["status"] == "duplicate"


def test_json_and_plain_text(client):
    r = client.post("/webhook", headers=H, json={"text": "삼성카드 승인 38,000원 11/09 19:02 배달의민족"})
    assert r.json()["status"] == "saved"
    r = client.post("/webhook?token=test-token&source=push", content="현대카드 승인 6,000원 11/09 08:00 GS25".encode(),
                    headers={"content-type": "text/plain"})
    assert r.json()["status"] == "saved"


def test_ignored_message(client):
    r = client.post("/webhook", headers=H, data={"text": "인증번호 [123456]"}).json()
    assert r["status"] == "ignored"
    assert len(client.get("/unparsed", headers=H).json()) == 1


def test_summary_and_export(client):
    for t in [SMS, "삼성카드 승인 38,000원 11/09 19:02 배달의민족", "KB국민카드 승인 50,000원 11/08 12:00 이마트"]:
        client.post("/webhook", headers=H, data={"text": t})
    s = client.get("/summary?month=2026-11", headers=H).json()
    assert s["total"] == 100500
    # 카페 12,500*0.5 + 배달 38,000*0.5 + 장보기 50,000*0.1 = 30,250
    assert s["savable_amount"] == 30250
    assert s["savable_pct"] == pytest.approx(30.1, abs=0.1)

    r = client.get("/export?month=2026-11", headers=H)
    assert r.status_code == 200
    import io
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["요약", "카테고리별", "일별", "상세내역", "월별추이"]
    assert wb["상세내역"].max_row == 4


def test_manual_and_patch(client):
    r = client.post("/transactions", headers=H, json={"merchant": "시장 현금", "amount": 8000}).json()
    assert client.patch(f"/transactions/{r['id']}", headers=H, json={"category": "장보기"}).status_code == 200
    txs = client.get("/transactions", headers=H).json()
    assert txs[0]["category"] == "장보기"


def test_query_params_only_and_exact_duplicate(client):
    # MacroDroid '쿼리 파라미터' 방식: 본문 없이 URL에 text/source/token
    params = {"token": "test-token", "text": SMS, "source": "sms"}
    assert client.post("/webhook", params=params).json()["status"] == "saved"
    # 같은 문자를 두 번째 매크로가 또 보냄 → 중복
    assert client.post("/webhook", params=params).json()["status"] == "duplicate"
    assert len(client.get("/transactions?month=2026-11", headers=H).json()) == 1
