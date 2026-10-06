# -*- coding: utf-8 -*-
"""index.html 을 만든다 — 글로벌 공통 지표 한 장.

조간 브리핑 참고자료에 걸리는 쪽이다. 시장 자료라 평일 날마다 돈다.

한 지표가 실패해도 나머지는 올라가고, 빠진 것은 화면에 적는다. 값이 틀리는
고장보다 조용히 사라지는 고장이 무섭다 — 차트팩에서 그것을 여러 번 겪었다.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import fetchers as F                                           # noqa: E402
import sources as S                                            # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "template.html"
OUTPUT = ROOT / "index.html"

TROUBLE: list[str] = []


def log(msg: str = "") -> None:
    print(msg, flush=True)
    if any(m in msg for m in ("[실패]", "[어긋남]")):
        TROUBLE.append(" ".join(msg.split()))


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def month_axis(today: datetime.date, n: int) -> list[str]:
    y, m = today.year, today.month
    out = []
    for i in range(n - 1, -1, -1):
        yy, mm = y, m - i
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append(f"{yy}-{mm:02d}")
    return out


def day_axis(series: list[dict[str, float]], since: str) -> list[str]:
    """받아 온 모든 계열에 한 번이라도 나온 날을 모아 축으로 삼는다.

    시장마다 쉬는 날이 달라 달력으로 만들면 빈 칸이 줄줄이 생긴다. 거꾸로
    한 계열의 날짜만 쓰면 그 시장이 쉰 날 다른 계열이 통째로 밀린다.
    """
    days: set[str] = set()
    for s in series:
        days |= {d for d in s if d >= since}
    return sorted(days)


def align(rows: dict[str, float], axis: list[str]) -> list[float | None]:
    return [rows.get(k) for k in axis]


def check(key: str, vals: list[float | None]) -> None:
    lo, hi = S.BOUNDS.get(key, (None, None))
    if lo is None:
        return
    bad = [v for v in vals if v is not None and not (lo <= v <= hi)]
    if bad:
        log(f"  [어긋남] {key} — 범위 {lo}~{hi} 를 벗어난 값 {len(bad)}개 "
            f"(예: {bad[0]})")


def collect(today: datetime.date) -> tuple[dict, dict, list[str]]:
    since_d = (today - datetime.timedelta(days=S.DAYS_BACK)).isoformat()
    months = month_axis(today, S.MONTHS_BACK)
    raw_daily: dict[str, dict[str, float]] = {}
    raw_monthly: dict[str, dict[str, float]] = {}
    warn: list[str] = []

    for key, name, sym, _dec, _unit in S.YAHOO:
        try:
            raw_daily[key] = F.yahoo(sym)
            log(f"  일별 {key:7} Yahoo {sym:9} {len(raw_daily[key]):4}점")
        except F.GrabError as exc:
            warn.append(f"{name} 을 받지 못했다")
            log(f"  [실패] {name} — {exc}")

    for key, name, fn in ((S.BUND10[0], S.BUND10[1], lambda: F.bund10()),
                          (S.JGB10[0], S.JGB10[1], lambda: F.jgb10(since_d)),
                          (S.SOFR[0], S.SOFR[1], lambda: F.sofr())):
        try:
            raw_daily[key] = fn()
            log(f"  일별 {key:7} {name:11} {len(raw_daily[key]):4}점")
        except F.GrabError as exc:
            warn.append(f"{name} 을 받지 못했다")
            log(f"  [실패] {name} — {exc}")

    for key, (name, skey) in S.EURIBOR.items():
        try:
            raw_monthly[key] = F.ecb("FM", skey, months[0])
            log(f"  월별 {key:7} ECB 유리보  {len(raw_monthly[key]):4}점")
        except F.GrabError as exc:
            warn.append(f"{name} 을 받지 못했다")
            log(f"  [실패] {name} — {exc}")

    key, name, table, item, _u = S.DUBAI
    try:
        raw_monthly[key] = F.ecos(table, item,
                                  months[0].replace("-", ""),
                                  months[-1].replace("-", ""))
        log(f"  월별 {key:7} ECOS 두바이유 {len(raw_monthly[key]):4}점")
    except F.GrabError as exc:
        warn.append("두바이유를 받지 못했다")
        log(f"  [실패] 두바이유 — {exc}")

    try:
        got = F.fao()
        for key, (name, col) in S.FAO_COLS.items():
            if col in got:
                raw_monthly[key] = got[col]
                log(f"  월별 {key:9} FAO {col:18} {len(got[col]):4}점")
    except F.GrabError as exc:
        warn.append("FAO 지수를 받지 못했다")
        log(f"  [실패] FAO — {exc}")

    days = day_axis(list(raw_daily.values()), since_d)
    data = {"meta": {"days": days, "months": months,
                     "asOf": today.isoformat()}}
    for key, rows in raw_daily.items():
        data[key] = align(rows, days)
        check(key, data[key])
    for key, rows in raw_monthly.items():
        data[key] = align(rows, months)
        check(key, data[key])
    return data, {"days": len(days), "months": len(months)}, warn


def last_of(data: dict, key: str) -> tuple[str | None, float | None]:
    axis = data["meta"]["days" if len(data.get(key) or []) ==
                        len(data["meta"]["days"]) else "months"]
    vals = data.get(key) or []
    for i in range(len(vals) - 1, -1, -1):
        if vals[i] is not None:
            return axis[i], vals[i]
    return None, None


NOTE = """<b>무엇을 모았나</b> 나라에 묶이지 않는 지표만 싣습니다. 나라별
거시지표는 <a href="https://tskang89.github.io/euro-chartpack/">주요국 경제
차트팩</a>이 맡습니다.
<br><br>
<b>축이 둘입니다.</b> 시장 자료는 날마다 움직이지만 몇몇은 월별로만 나옵니다 —
두바이유(한국은행 ECOS), FAO 지수, 유리보(ECB 가 월평균만 공표)입니다. 월별
값을 일별 축에 늘어놓으면 계단이 되어 '한 달 내내 값이 같았다'로 읽히므로
따로 그립니다. 그림 제목 밑에 일별인지 월별인지 적었습니다.
<br><br>
<b>자료</b> 선물·지수는 Yahoo Finance 종가, 독일 10년물은 분데스방크 Svensson
수익률곡선, 일본 10년물은 일본 재무성, SOFR 은 뉴욕 연준, 유리보는 ECB
데이터 포털(산출은 EMMI), 두바이유는 한국은행 ECOS 국제상품가격,
FAO 지수는 국제연합 식량농업기구입니다.
<br><br>
<b>발틱운임지수(BDI)는 넣지 못했습니다.</b> 발틱거래소가 라이선스로 묶어 두어
공개 계열이 없습니다. Yahoo 의 BDRY 는 건화물 운임 <b>선물 ETF</b> 라 지수가
아니어서, 대용물을 BDI 라는 이름으로 올리지 않았습니다.
<br><br>
<b>S&amp;P GSCI 농산물지수도 넣지 못했습니다.</b> 공개 창구에 과거치가 하루치만
있어 선을 그릴 수 없습니다. 대신 같은 자리에 FAO 곡물지수를 두었습니다."""


def build(today: datetime.date) -> str:
    log(f"글로벌 지표 수집 — {today}")
    data, size, warn = collect(today)
    if len(data) <= 1:
        raise RuntimeError("하나도 받지 못했다 — 쪽을 쓰지 않는다")

    kpi = []
    for key, name, _s, dec, unit in S.YAHOO[:4]:
        day, v = last_of(data, key)
        if v is not None:
            kpi.append((name, f"{v:,.{dec}f}", unit, day))

    stamp = f'{today.year}년 {today.month}월 {today.day}일 기준'
    warn_html = ""
    if warn:
        warn_html = ('<div class="warn"><b>일부를 받지 못했습니다.</b> '
                     + " / ".join(esc(w) for w in warn) + "</div>")

    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("__DATA__", json.dumps(data, ensure_ascii=False,
                                               separators=(",", ":")))
    page = page.replace("__STAMP__", esc(stamp))
    page = page.replace("__WARN__", warn_html)
    page = page.replace("__NOTE__", NOTE)
    page = page.replace("__OPS__", ops_blob(today, data, warn))
    log(f"\n일별 축 {size['days']}일 · 월별 축 {size['months']}달")
    return page


def ops_blob(today, data, warn) -> str:
    keys = [k for k in data if k != "meta"]
    ops = {
        "built": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%MZ"),
        "asOf": today.isoformat(),
        "series": len(keys),
        "last": {k: list(last_of(data, k)) for k in keys},
        "warn": [" ".join(w.split()) for w in warn],
        "trouble": TROUBLE,
    }
    return json.dumps(ops, ensure_ascii=False).replace("<", "\\u003c")


def main() -> int:
    ap = argparse.ArgumentParser(description="글로벌 차트팩")
    ap.add_argument("--check", action="store_true", help="쓰지 않고 만들어만 본다")
    ap.add_argument("--date", help="기준일을 바꿔 본다 (YYYY-MM-DD)")
    args = ap.parse_args()
    today = (datetime.date.fromisoformat(args.date) if args.date
             else datetime.date.today())
    page = build(today)
    if args.check:
        log("--check: 파일을 쓰지 않았다.")
        return 0
    OUTPUT.write_text(page, encoding="utf-8")
    log(f"index.html 갱신 — {len(page):,}자")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
