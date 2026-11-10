"""FastAPI 서버: MacroDroid가 보낸 카드 알림을 받아 SQLite에 쌓고 엑셀을 갱신한다.

실행:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config, db
from .categorize import categorize, saving_rate
from .excel import export_month
from .parser import parse_message

@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="자동 가계부 (MacroDroid → FastAPI → SQLite → Excel)", version="1.0.0", lifespan=lifespan)


def check_token(x_token: Optional[str] = Header(default=None), token: Optional[str] = Query(default=None)) -> None:
    if not config.API_TOKEN:
        raise HTTPException(500, "서버 .env에 API_TOKEN을 설정하세요")
    given = x_token or token or ""
    if not secrets.compare_digest(given, config.API_TOKEN):
        raise HTTPException(401, "invalid token")


async def _read_payload(request: Request) -> dict:
    """MacroDroid HTTP 요청은 JSON / form / text 어떤 형식으로 보내도 받는다.

    문자 본문에 줄바꿈·따옴표가 들어 있으면 JSON이 깨지기 쉬워서
    MacroDroid에서는 form(application/x-www-form-urlencoded) 방식을 권장한다.
    """
    ctype = request.headers.get("content-type", "")
    data: dict = dict(request.query_params)          # ?text=...&source=... 방식도 허용
    data.pop("token", None)
    if "application/json" in ctype:
        try:
            body = await request.json()
            data.update(body if isinstance(body, dict) else {"text": str(body)})
        except Exception:
            data["text"] = (await request.body()).decode("utf-8", "ignore")
    elif "form" in ctype:
        form = await request.form()
        data.update({k: str(v) for k, v in form.items()})
    else:
        raw = (await request.body()).decode("utf-8", "ignore").strip()
        if raw:
            data["text"] = raw
    return data


def _refresh_excel(month: str) -> None:
    export_month(month)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "time": datetime.now().isoformat(timespec="seconds")}


@app.post("/webhook", dependencies=[Depends(check_token)])
async def webhook(request: Request, background: BackgroundTasks) -> dict:
    """MacroDroid가 호출하는 엔드포인트.

    필드: text(필수, 알림 본문) / title(알림 제목) / sender(발신번호·앱이름) / source(sms|push)
    """
    p = await _read_payload(request)
    title = p.get("title", "") or ""
    text = "\n".join(x for x in (title, p.get("text", "") or "") if x)
    sender = p.get("sender", "") or p.get("app", "") or ""
    source = (p.get("source") or "sms").lower()

    parsed = parse_message(text, sender_hint=sender)
    if not parsed:
        db.log_raw(source, sender, text, "ignored")
        return {"status": "ignored", "reason": "결제 알림 형식이 아님"}

    paid_at = parsed.paid_at or datetime.now().replace(second=0, microsecond=0)
    amount = -parsed.amount if parsed.is_cancel else parsed.amount

    dup = db.find_duplicate(parsed.card, amount, paid_at, source)
    if dup:
        db.log_raw(source, sender, text, "duplicate")
        return {"status": "duplicate", "id": dup}

    category = categorize(parsed.merchant)
    tx_id = db.insert_transaction(
        paid_at=paid_at, card=parsed.card, card_last4=parsed.card_last4, merchant=parsed.merchant,
        amount=amount, is_cancel=parsed.is_cancel, installment=parsed.installment,
        category=category, source=source, raw_text=text,
    )
    if tx_id is None:  # 같은 문자를 두 매크로가 동시에 보낸 경우 등 완전히 같은 결제
        db.log_raw(source, sender, text, "duplicate")
        return {"status": "duplicate"}
    db.log_raw(source, sender, text, "parsed")
    month = paid_at.strftime("%Y-%m")
    background.add_task(_refresh_excel, month)
    return {"status": "saved", "id": tx_id, "category": category, **parsed.to_dict(), "amount": amount}


class ManualTx(BaseModel):
    merchant: str
    amount: int
    paid_at: Optional[datetime] = None
    category: Optional[str] = None
    card: str = "현금"
    memo: str = ""


@app.post("/transactions", dependencies=[Depends(check_token)])
def add_manual(tx: ManualTx, background: BackgroundTasks) -> dict:
    """현금·계좌이체처럼 알림이 없는 지출을 직접 추가."""
    paid_at = tx.paid_at or datetime.now()
    category = tx.category or categorize(tx.merchant)
    tx_id = db.insert_transaction(
        paid_at=paid_at, card=tx.card, card_last4="", merchant=tx.merchant, amount=tx.amount,
        is_cancel=tx.amount < 0, installment="", category=category, source="manual", memo=tx.memo,
    )
    background.add_task(_refresh_excel, paid_at.strftime("%Y-%m"))
    return {"status": "saved", "id": tx_id, "category": category}


class TxPatch(BaseModel):
    category: Optional[str] = None
    memo: Optional[str] = None
    merchant: Optional[str] = None


@app.patch("/transactions/{tx_id}", dependencies=[Depends(check_token)])
def patch_tx(tx_id: int, body: TxPatch) -> dict:
    if not db.update_transaction(tx_id, **body.model_dump()):
        raise HTTPException(404, "not found or nothing to update")
    return {"status": "updated"}


@app.delete("/transactions/{tx_id}", dependencies=[Depends(check_token)])
def delete_tx(tx_id: int) -> dict:
    if not db.delete_transaction(tx_id):
        raise HTTPException(404, "not found")
    return {"status": "deleted"}


def _month_or_now(month: Optional[str]) -> str:
    return month or datetime.now().strftime("%Y-%m")


@app.get("/transactions", dependencies=[Depends(check_token)])
def list_tx(month: Optional[str] = None) -> list[dict]:
    return db.list_transactions(_month_or_now(month))


@app.get("/summary", dependencies=[Depends(check_token)])
def summary(month: Optional[str] = None) -> dict:
    """이번 달 총지출 / 카테고리별 / 절약 가능 퍼센트."""
    month = _month_or_now(month)
    txs = db.list_transactions(month)
    total = sum(t["amount"] for t in txs)
    cats: dict[str, int] = {}
    for t in txs:
        cats[t["category"]] = cats.get(t["category"], 0) + t["amount"]
    savable = sum(max(0, a) * saving_rate(c) for c, a in cats.items())
    return {
        "month": month,
        "total": total,
        "count": len(txs),
        "budget": config.MONTHLY_BUDGET,
        "budget_used_pct": round(total / config.MONTHLY_BUDGET * 100, 1) if config.MONTHLY_BUDGET else None,
        "savable_amount": round(savable),
        "savable_pct": round(savable / total * 100, 1) if total > 0 else 0,
        "by_category": dict(sorted(cats.items(), key=lambda x: -x[1])),
    }


@app.get("/export", dependencies=[Depends(check_token)])
def export(month: Optional[str] = None) -> FileResponse:
    """엑셀 파일 다운로드 (휴대폰 브라우저에서도 열림)."""
    month = _month_or_now(month)
    path = export_month(month)
    return FileResponse(path, filename=path.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/unparsed", dependencies=[Depends(check_token)])
def unparsed(limit: int = 30) -> list[dict]:
    """결제로 인식되지 않은 알림 원문 (파서 규칙 보완용)."""
    return db.recent_raw(limit, status="ignored")
