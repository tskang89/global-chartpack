# -*- coding: utf-8 -*-
"""원자재 가격을 출처별로 받아 온다. 모두 {날짜: 값} 또는 {YYYY-MM: 값}.

출처가 갈린 까닭을 여기 적어 둔다. 한 군데서 다 받을 수 있었다면 그렇게 했다.

  Yahoo Finance   선물·지수 대부분. 일별.
  분데스방크       독일 10년물. Yahoo 에 쓸 만한 분트 금리가 없다.
  일본 재무성      일본 10년물. 같은 까닭.
  뉴욕 연준        SOFR. 공식 창구가 API 로 열려 있다.
  ECB             유리보. **월평균만 있다** — 일별 계열(D.…)은 404 다.
  한국은행 ECOS    두바이유. Yahoo 에 두바이 선물이 없다. 월별.
  FAO             식량가격지수·곡물지수. 월별.

**BDI 는 넣지 못했다.** 발틱거래소가 라이선스로 묶어 두어 무료 계열이 없다
(발틱거래소·한국해양진흥공사·KMI 모두 막힘, 2026-10-06 확인). Yahoo 의
BDRY 는 건화물 운임 **선물 ETF** 라 지수가 아니다 — 대용물을 'BDI' 라는
이름으로 올리면 읽는 사람을 속이게 된다.
"""

from __future__ import annotations

import csv
import datetime
import io
import json
import os
import re
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
TIMEOUT = 60
RETRIES = 3
PACE = 0.35


class GrabError(RuntimeError):
    pass


def _get(url: str, **kw) -> requests.Response:
    last = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, timeout=TIMEOUT,
                             headers={"User-Agent": UA, **kw.pop("headers", {})},
                             **kw)
        except requests.RequestException as exc:
            last = exc
        else:
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        if attempt + 1 < RETRIES:
            time.sleep(2 * (attempt + 1))
    raise GrabError(f"{url.split('/')[2]}: {last}")


# ------------------------------------------------------------------ Yahoo
YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{s}"
         "?range={rng}&interval=1d")


def yahoo(symbol: str, rng: str = "2y") -> dict[str, float]:
    """일별 종가. {YYYY-MM-DD: 값}.

    조정종가가 아니라 종가를 쓴다. 선물·지수라 배당 조정이 뜻이 없다.
    """
    doc = _get(YAHOO.format(s=symbol.replace("^", "%5E"), rng=rng)).json()
    res = (doc.get("chart") or {}).get("result")
    if not res:
        err = ((doc.get("chart") or {}).get("error") or {}).get("description")
        raise GrabError(f"Yahoo {symbol}: {err or '빈 응답'}")
    r = res[0]
    stamps = r.get("timestamp") or []
    closes = (r["indicators"]["quote"][0] or {}).get("close") or []
    out = {}
    for ts, v in zip(stamps, closes):
        if v is None:
            continue
        out[datetime.datetime.fromtimestamp(ts, datetime.UTC)
            .strftime("%Y-%m-%d")] = float(v)
    if not out:
        raise GrabError(f"Yahoo {symbol}: 값이 하나도 없다")
    time.sleep(PACE)
    return out


# ----------------------------------------------------------- 분데스방크
# Svensson 수익률곡선(일별) 10년물. 조간 브리핑이 쓰는 것과 같은 계열이다.
BBK = ("https://api.statistiken.bundesbank.de/rest/data/BBSIS/"
       "D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A")


# --------------------------------------------------------- 일본 재무성
# 전 기간 파일(1.2MB). 머리글이 `Date,1Y,2Y,…` 이고 값은 '%' 다.
MOF = ("https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
       "historical/jgbcme_all.csv")


# ------------------------------------------------------------ 뉴욕 연준
NYFED = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/{n}.json"


# ------------------------------------------------------------------ ECB
ECB = "https://data-api.ecb.europa.eu/service/data/{flow}/{key}"


# ----------------------------------------------------------------- ECOS
ECOS = ("https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/{rows}/"
        "{table}/{cycle}/{start}/{end}/{item}")


def ecos(table: str, item: str, start: str, end: str,
         cycle: str = "M") -> dict[str, float]:
    key = os.environ.get("ECOS_API_KEY")
    if not key:
        raise GrabError("ECOS_API_KEY 가 없다")
    url = ECOS.format(key=key, rows=700, table=table, cycle=cycle,
                      start=start, end=end, item=item)
    for attempt in range(RETRIES):
        doc = _get(url).json()
        rows = (doc.get("StatisticSearch") or {}).get("row")
        if rows:
            return {f"{r['TIME'][:4]}-{r['TIME'][4:6]}": float(r["DATA_VALUE"])
                    for r in rows if r.get("DATA_VALUE") not in (None, "", "-")}
        why = doc.get("RESULT") or {}
        # INFO-200 은 '자료 없음'인데 호출이 몰렸을 때도 같은 것이 온다.
        # 차트팩에서 같은 일로 10년물이 통째로 빠진 적이 있다(2026-10-05).
        if why.get("CODE") == "INFO-200" and attempt + 1 < RETRIES:
            time.sleep(3 * (attempt + 1))
            continue
        raise GrabError(f"ECOS {table}/{item}: "
                        f"{why.get('MESSAGE', '빈 응답')}")
    raise GrabError(f"ECOS {table}/{item}: 거듭 물어도 비었다")


# ------------------------------------------------------------------ FAO
# 머리글이 셋째 줄에 있다(첫 줄 제목, 둘째 줄 기준연도). 'Date' 가 YYYY-MM.
FAO = ("https://www.fao.org/media/docs/worldfoodsituationlibraries/"
       "wfs-library/food_price_indices_data.csv")


def fao() -> dict[str, dict[str, float]]:
    text = _get(FAO).text
    rows = list(csv.reader(io.StringIO(text)))
    head, out = None, {}
    for r in rows:
        if not r or not r[0].strip():
            continue
        if head is None:
            if r[0].strip() == "Date":
                head = [c.strip() for c in r]
            continue
        if not re.fullmatch(r"\d{4}-\d{2}", r[0].strip()):
            continue
        for col in ("Food Price Index", "Cereals"):
            if col not in head:
                continue
            v = r[head.index(col)].strip()
            if v:
                try:
                    out.setdefault(col, {})[r[0].strip()] = float(v)
                except ValueError:
                    pass
    if not out.get("Food Price Index"):
        raise GrabError("FAO: 식량가격지수를 읽지 못했다")
    return out
