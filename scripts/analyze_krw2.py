"""원화 급강세의 '정책 주도' 지문 검증 — 일회성 애드혹 스크립트 (로그 출력 전용).

검증 항목:
1. 최근 60거래일 아시아 통화·달러인덱스 대비 원화의 상대 강세 (원화만 유독 강한가)
2. 원/달러 최대 일간 하락일 목록 (개입·발표 날짜와의 일치 여부)
3. 원화 일간 변동의 달러인덱스 설명력 (정책성 고유 움직임 비중)
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

PAIRS = {
    "KRW=X": "원/달러",
    "JPY=X": "엔/달러",
    "CNY=X": "위안/달러",
    "TWD=X": "대만달러/달러",
    "SGD=X": "싱가포르달러/달러",
    "DX-Y.NYB": "달러인덱스",
}
WINDOW = 60


def fetch(symbol: str) -> pd.Series:
    raw = yf.download(symbol, period="6mo", interval="1d",
                      auto_adjust=False, progress=False)
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna()


def main() -> int:
    series = {name: fetch(sym) for sym, name in PAIRS.items()}

    print(f"── 1. 최근 {WINDOW}거래일 변화율 (음수 = 해당 통화 강세/달러 약세) ──")
    for name, s in series.items():
        if len(s) > WINDOW:
            chg = (s.iloc[-1] / s.iloc[-1 - WINDOW] - 1) * 100
            print(f"{name:<10} {float(chg):+7.2f}%   (현재 {float(s.iloc[-1]):,.2f})")
    print()

    krw = series["원/달러"]
    daily = krw.pct_change() * 100
    print("── 2. 원/달러 최대 일간 하락 10일 (최근 6개월) ──")
    for dt, v in daily.nsmallest(10).items():
        print(f"{dt.date()}  {float(v):+.2f}%  (종가 {float(krw[dt]):,.1f})")
    print()

    dxy = series["달러인덱스"].pct_change() * 100
    joined = pd.concat([daily.rename("krw"), dxy.rename("dxy")], axis=1).dropna()
    recent = joined.tail(WINDOW)
    corr = float(recent["krw"].corr(recent["dxy"]))
    beta = float(recent["krw"].cov(recent["dxy"]) / recent["dxy"].var())
    krw_total = float((krw.iloc[-1] / krw.iloc[-1 - WINDOW] - 1) * 100)
    dxy_total = float(
        (series["달러인덱스"].iloc[-1] / series["달러인덱스"].iloc[-1 - WINDOW] - 1) * 100
    )
    explained = beta * dxy_total
    print("── 3. 달러인덱스 설명력 (최근 60거래일) ──")
    print(f"상관계수 {corr:+.2f} · 베타 {beta:+.2f}")
    print(f"원/달러 총 변화 {krw_total:+.2f}% 중 달러인덱스로 설명되는 몫 {explained:+.2f}%p")
    print(f"→ 원화 고유(달러와 무관한) 움직임: {krw_total - explained:+.2f}%p")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
