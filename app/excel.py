"""월간 가계부 엑셀 리포트 생성 (openpyxl).

시트 구성
  요약        총지출, 일평균, 예산 대비, 절약 가능액/퍼센트, 전월 대비, 절약 팁
  카테고리별   SUMIFS 수식으로 상세내역을 집계 + 절약률(파란 글씨, 직접 수정 가능) + 차트
  일별        날짜별 지출·누적 vs 예산 페이스 + 차트
  상세내역     결제 한 건 = 한 줄 (카테고리 셀을 바꾸면 다른 시트가 자동 재계산)
  월별추이     DB에 쌓인 모든 달의 총지출 + 차트
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import config, db
from .categorize import all_categories, saving_rate

FONT = "맑은 고딕"
WON = '#,##0"원";[Red]-#,##0"원";"-"'
PCT = '0.0%;[Red]-0.0%;"-"'
HEADER_FILL = PatternFill("solid", start_color="1F3864")
TITLE_FONT = Font(name=FONT, size=16, bold=True, color="1F3864")
HEADER_FONT = Font(name=FONT, bold=True, color="FFFFFF")
BASE_FONT = Font(name=FONT, size=10)
INPUT_FONT = Font(name=FONT, size=10, color="0000FF")      # 사용자가 바꿔도 되는 값
LINK_FONT = Font(name=FONT, size=10, color="008000")       # 다른 시트 참조
BOLD = Font(name=FONT, size=10, bold=True)
KEY_FILL = PatternFill("solid", start_color="FFF2CC")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
WEEKDAYS = "월화수목금토일"


def _header(ws, row: int, labels: list[str], widths: list[int] | None = None) -> None:
    for i, label in enumerate(labels, start=1):
        c = ws.cell(row=row, column=i, value=label)
        c.font, c.fill, c.border = HEADER_FONT, HEADER_FILL, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center")
    if widths:
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _style_body(ws, min_row: int, max_row: int, max_col: int) -> None:
    for row in ws.iter_rows(min_row=min_row, max_row=max_row, max_col=max_col):
        for c in row:
            if c.font.name != FONT:
                c.font = BASE_FONT
            c.border = BORDER


def _prev_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def build_workbook(month: str) -> Workbook:
    txs = db.list_transactions(month)
    totals = db.monthly_totals()
    year, mon = map(int, month.split("-"))
    days_in_month = calendar.monthrange(year, mon)[1]
    cats = all_categories()

    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "요약"
    ws_cat = wb.create_sheet("카테고리별")
    ws_day = wb.create_sheet("일별")
    ws_tx = wb.create_sheet("상세내역")
    ws_trend = wb.create_sheet("월별추이")

    # ---------------- 상세내역 ----------------
    _header(ws_tx, 1, ["결제일시", "날짜", "요일", "카드", "가맹점", "카테고리", "금액", "할부", "출처", "메모", "ID"],
            [17, 12, 6, 10, 28, 13, 13, 8, 7, 20, 6])
    for r, t in enumerate(txs, start=2):
        paid = datetime.fromisoformat(t["paid_at"])
        ws_tx.cell(r, 1, paid).number_format = "yyyy-mm-dd hh:mm"
        ws_tx.cell(r, 2, paid.date()).number_format = "yyyy-mm-dd"
        ws_tx.cell(r, 3, WEEKDAYS[paid.weekday()])
        ws_tx.cell(r, 4, f"{t['card']}{'(' + t['card_last4'] + ')' if t['card_last4'] else ''}")
        ws_tx.cell(r, 5, t["merchant"] + (" [취소]" if t["is_cancel"] else ""))
        ws_tx.cell(r, 6, t["category"]).font = INPUT_FONT
        ws_tx.cell(r, 7, t["amount"]).number_format = WON
        ws_tx.cell(r, 8, t["installment"])
        ws_tx.cell(r, 9, t["source"])
        ws_tx.cell(r, 10, t["memo"])
        ws_tx.cell(r, 11, t["id"])
    last_tx = max(2, len(txs) + 1)
    _style_body(ws_tx, 2, last_tx, 11)
    if txs:
        ws_tx.auto_filter.ref = f"A1:K{last_tx}"
    # 카테고리 드롭다운 (직접 수정하면 다른 시트가 재계산됨)
    cat_list_ref = f"카테고리별!$A$2:$A${len(cats) + 1}"
    dv = DataValidation(type="list", formula1=f"={cat_list_ref}", allow_blank=False)
    ws_tx.add_data_validation(dv)
    dv.add(f"F2:F{max(last_tx, 500)}")
    TX_AMT = "상세내역!$G:$G"
    TX_CAT = "상세내역!$F:$F"
    TX_DATE = "상세내역!$B:$B"

    # ---------------- 카테고리별 ----------------
    _header(ws_cat, 1, ["카테고리", "지출액", "비중", "건수", "절약률(수정가능)", "절약 가능액", "절약 후 지출"],
            [14, 14, 9, 7, 15, 14, 14])
    n = len(cats)
    for i, cat in enumerate(cats, start=2):
        ws_cat.cell(i, 1, cat)
        ws_cat.cell(i, 2, f"=SUMIFS({TX_AMT},{TX_CAT},A{i})").number_format = WON
        ws_cat.cell(i, 3, f"=IF($B${n + 2}=0,0,B{i}/$B${n + 2})").number_format = PCT
        ws_cat.cell(i, 4, f"=COUNTIFS({TX_CAT},A{i})")
        c = ws_cat.cell(i, 5, saving_rate(cat))
        c.number_format, c.font = "0%", INPUT_FONT
        ws_cat.cell(i, 6, f"=MAX(0,B{i})*E{i}").number_format = WON
        ws_cat.cell(i, 7, f"=B{i}-F{i}").number_format = WON
    tr = n + 2
    ws_cat.cell(tr, 1, "합계").font = BOLD
    for col, f in ((2, f"=SUM(B2:B{tr - 1})"), (4, f"=SUM(D2:D{tr - 1})"),
                   (6, f"=SUM(F2:F{tr - 1})"), (7, f"=SUM(G2:G{tr - 1})")):
        c = ws_cat.cell(tr, col, f)
        c.font = BOLD
        if col != 4:
            c.number_format = WON
    ws_cat.cell(tr, 3, f"=IF(B{tr}=0,0,1)").number_format = PCT
    ws_cat.cell(tr, 5, f"=IF(B{tr}=0,0,F{tr}/B{tr})").number_format = PCT
    _style_body(ws_cat, 2, tr, 7)
    for col in range(1, 8):
        ws_cat.cell(tr, col).fill = KEY_FILL

    pie = PieChart()
    pie.title = "카테고리별 지출 비중"
    pie.add_data(Reference(ws_cat, min_col=2, min_row=1, max_row=tr - 1), titles_from_data=True)
    pie.set_categories(Reference(ws_cat, min_col=1, min_row=2, max_row=tr - 1))
    pie.dataLabels = DataLabelList()
    pie.dataLabels.showPercent = True
    for attr in ("showVal", "showCatName", "showSerName", "showLegendKey"):
        setattr(pie.dataLabels, attr, False)
    pie.height, pie.width = 9, 13
    ws_cat.add_chart(pie, "I2")

    bar = BarChart()
    bar.type = "bar"
    bar.title = "지출 vs 절약 후 지출"
    bar.add_data(Reference(ws_cat, min_col=2, min_row=1, max_row=tr - 1), titles_from_data=True)
    bar.add_data(Reference(ws_cat, min_col=7, min_row=1, max_row=tr - 1), titles_from_data=True)
    bar.set_categories(Reference(ws_cat, min_col=1, min_row=2, max_row=tr - 1))
    bar.height, bar.width = 10, 13
    ws_cat.add_chart(bar, "I21")

    # ---------------- 일별 ----------------
    _header(ws_day, 1, ["날짜", "요일", "지출", "누적 지출", "예산 페이스"], [12, 6, 13, 14, 14])
    for d in range(1, days_in_month + 1):
        r = d + 1
        day = date(year, mon, d)
        ws_day.cell(r, 1, day).number_format = "mm-dd"
        ws_day.cell(r, 2, WEEKDAYS[day.weekday()])
        ws_day.cell(r, 3, f"=SUMIFS({TX_AMT},{TX_DATE},A{r})").number_format = WON
        ws_day.cell(r, 4, f"=SUM($C$2:C{r})").number_format = WON
        c = ws_day.cell(r, 5, f"=요약!$C$6/{days_in_month}*{d}")
        c.number_format, c.font = WON, LINK_FONT
        if day.weekday() >= 5:
            for col in (1, 2):
                ws_day.cell(r, col).font = Font(name=FONT, size=10, color="C00000")
    last_day = days_in_month + 1
    _style_body(ws_day, 2, last_day, 5)
    line = LineChart()
    line.title = "누적 지출 vs 예산 페이스"
    line.add_data(Reference(ws_day, min_col=4, min_row=1, max_row=last_day), titles_from_data=True)
    line.add_data(Reference(ws_day, min_col=5, min_row=1, max_row=last_day), titles_from_data=True)
    line.set_categories(Reference(ws_day, min_col=1, min_row=2, max_row=last_day))
    line.height, line.width = 9, 18
    ws_day.add_chart(line, "G2")
    dbar = BarChart()
    dbar.title = "일별 지출"
    dbar.add_data(Reference(ws_day, min_col=3, min_row=1, max_row=last_day), titles_from_data=True)
    dbar.set_categories(Reference(ws_day, min_col=1, min_row=2, max_row=last_day))
    dbar.legend = None
    dbar.height, dbar.width = 8, 18
    ws_day.add_chart(dbar, "G21")

    # ---------------- 월별추이 ----------------
    _header(ws_trend, 1, ["월", "총지출", "건수", "전월 대비"], [10, 14, 7, 11])
    for i, t in enumerate(totals, start=2):
        ws_trend.cell(i, 1, t["month"])
        ws_trend.cell(i, 2, t["total"]).number_format = WON
        ws_trend.cell(i, 3, t["cnt"])
        if i > 2:
            ws_trend.cell(i, 4, f"=IF(B{i - 1}=0,0,B{i}/B{i - 1}-1)").number_format = PCT
    last_trend = max(2, len(totals) + 1)
    _style_body(ws_trend, 2, last_trend, 4)
    if totals:
        tbar = BarChart()
        tbar.title = "월별 총지출"
        tbar.add_data(Reference(ws_trend, min_col=2, min_row=1, max_row=last_trend), titles_from_data=True)
        tbar.set_categories(Reference(ws_trend, min_col=1, min_row=2, max_row=last_trend))
        tbar.legend = None
        tbar.height, tbar.width = 8, 14
        ws_trend.add_chart(tbar, "F2")

    # ---------------- 요약 ----------------
    prev = _prev_month(month)
    prev_total = next((t["total"] for t in totals if t["month"] == prev), 0)
    today = date.today()
    if (today.year, today.month) == (year, mon):
        elapsed = today.day
    elif (today.year, today.month) > (year, mon):
        elapsed = days_in_month
    else:
        elapsed = 1

    ws_sum.column_dimensions["A"].width = 3
    ws_sum.column_dimensions["B"].width = 22
    ws_sum.column_dimensions["C"].width = 18
    ws_sum.column_dimensions["D"].width = 60
    ws_sum["B2"] = f"{year}년 {mon}월 자동 가계부"
    ws_sum["B2"].font = TITLE_FONT
    ws_sum["B3"] = f"생성: {datetime.now():%Y-%m-%d %H:%M} · 카드 결제 알림 자동 수집"
    ws_sum["B3"].font = Font(name=FONT, size=9, color="808080")

    rows = [
        ("총 지출", f"=카테고리별!B{tr}", WON, LINK_FONT, "취소 건은 음수로 반영"),
        ("결제 건수", f"=카테고리별!D{tr}", "0\"건\"", LINK_FONT, ""),
        ("한 달 예산", config.MONTHLY_BUDGET, WON, INPUT_FONT, "파란 숫자는 직접 바꿔도 됩니다 (.env MONTHLY_BUDGET 기본값)"),
        ("예산 사용률", "=IF(C6=0,0,C4/C6)", PCT, BASE_FONT, "100% 넘으면 예산 초과"),
        ("남은 예산", "=IF(C6=0,0,C6-C4)", WON, BASE_FONT, ""),
        ("경과 일수", elapsed, "0\"일\"", INPUT_FONT, f"이번 달 {days_in_month}일 중"),
        ("일평균 지출", "=IF(C9=0,0,C4/C9)", WON, BASE_FONT, ""),
        ("월말 예상 지출", f"=C10*{days_in_month}", WON, BASE_FONT, "지금 속도로 쓰면"),
        ("절약 가능액", f"=카테고리별!F{tr}", WON, LINK_FONT, "카테고리별 절약률 × 지출액"),
        ("절약 가능 퍼센트", "=IF(C4=0,0,C12/C4)", PCT, BOLD, "이번 달 지출 중 줄일 수 있는 비율(추정)"),
        ("전월 지출", prev_total, WON, BASE_FONT, f"{prev} 기준"),
        ("전월 대비 증감", "=IF(C14=0,0,C4/C14-1)", PCT, BASE_FONT, ""),
    ]
    for i, (label, value, fmt, font, note) in enumerate(rows, start=4):
        ws_sum.cell(i, 2, label).font = BOLD
        c = ws_sum.cell(i, 3, value)
        c.number_format, c.font = fmt, font
        c.alignment = Alignment(horizontal="right")
        ws_sum.cell(i, 4, note).font = Font(name=FONT, size=9, color="808080")
        for col in (2, 3, 4):
            ws_sum.cell(i, col).border = BORDER
    for col in (2, 3):
        ws_sum.cell(13, col).fill = KEY_FILL

    # 절약 팁 (파이썬으로 계산한 상위 카테고리)
    by_cat: dict[str, int] = {}
    for t in txs:
        by_cat[t["category"]] = by_cat.get(t["category"], 0) + t["amount"]
    tips = sorted(((c, a, a * saving_rate(c)) for c, a in by_cat.items() if a > 0), key=lambda x: -x[2])[:3]
    tip_row = 4 + len(rows) + 1
    ws_sum.cell(tip_row, 2, "이번 달 절약 포인트 TOP 3").font = Font(name=FONT, size=12, bold=True, color="1F3864")
    if not tips:
        ws_sum.cell(tip_row + 1, 2, "아직 결제 내역이 없습니다.").font = BASE_FONT
    for k, (cat, amt, save) in enumerate(tips, start=1):
        cnt = sum(1 for t in txs if t["category"] == cat)
        ws_sum.cell(tip_row + k, 2, f"{k}. {cat}").font = BOLD
        c = ws_sum.cell(tip_row + k, 3, round(save))
        c.number_format, c.font = WON, BASE_FONT
        ws_sum.cell(tip_row + k, 4,
                    f"{cnt}건 {amt:,}원 → 절약률 {saving_rate(cat):.0%} 적용 시 약 {round(save):,}원 아낄 수 있음"
                    ).font = BASE_FONT

    ws_sum.cell(tip_row + 5, 2, "범례: 파란 글씨=직접 수정 가능 / 초록 글씨=다른 시트 참조").font = \
        Font(name=FONT, size=9, color="808080")
    ws_sum.sheet_view.showGridLines = False
    return wb


def export_month(month: str) -> Path:
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.EXPORT_DIR / f"{month}_가계부.xlsx"
    build_workbook(month).save(path)
    return path
