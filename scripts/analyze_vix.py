"""장기 저변동(VIX 소외) 국면 이후 변동성 폭발 여부 — 일회성 애드혹 (로그 출력 전용).

신호 정의(오늘과 유사): VIX 60일 평균 < 15 이고, 종가 25 이상 스파이크가
250거래일(약 1년) 이상 없었던 첫날. 에피소드별로 이후 스파이크까지의 시간과
12개월 내 최대 VIX·S&P500 최대 낙폭을 계산한다.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

MA_WIN = 60
CALM_TH = 15.0  # 저변동 판정 (60일 평균)
SPIKE_TH = 25.0  # 변동성 이벤트 판정
BIG_SPIKE_TH = 30.0
NO_SPIKE_DAYS = 250  # 신호 조건: 이 기간 이상 스파이크 부재
EPISODE_GAP = 120
FWD_1Y = 253


def fetch(sym: str) -> pd.Series:
    raw = yf.download(sym, period="max", interval="1d", auto_adjust=False, progress=False)
    close = raw["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna()


def days_since_spike(vix: pd.Series) -> pd.Series:
    """각 시점에서 직전 종가 25 이상까지의 거래일 수 (그 전이면 -1)."""
    out, last = [], None
    for i, v in enumerate(vix.values):
        if v >= SPIKE_TH:
            last = i
        out.append(i - last if last is not None else -1)
    return pd.Series(out, index=vix.index)


def main() -> int:
    vix = fetch("^VIX")
    spx = fetch("^GSPC")
    ma = vix.rolling(MA_WIN).mean()
    ds = days_since_spike(vix)
    signal = (ma < CALM_TH) & (ds >= NO_SPIKE_DAYS)

    idx = [int(i) for i in range(len(vix)) if bool(signal.iloc[i])]
    episodes: list[int] = []
    prev = None
    for p in idx:
        if prev is None or p - prev > EPISODE_GAP:
            episodes.append(p)
        prev = p

    print(f"데이터: {vix.index[0].date()} ~ {vix.index[-1].date()} · 오늘 VIX {float(vix.iloc[-1]):.1f} "
          f"(60일 평균 {float(ma.iloc[-1]):.1f}, 마지막 스파이크 후 {int(ds.iloc[-1])}거래일)")
    print(f"신호 = 60일 평균<{CALM_TH:.0f} & {NO_SPIKE_DAYS}일+ 무스파이크 · 에피소드 {len(episodes)}회")
    print()
    print("신호일 | VIX | ≥25까지 | 스파이크일 | ≥30까지 | 12M내 최대VIX | 12M SPX최대낙폭")
    stats: list[dict] = []
    for p in episodes:
        d0 = vix.index[p]
        fut = vix.iloc[p + 1:]
        hit25 = fut[fut >= SPIKE_TH]
        hit30 = fut[fut >= BIG_SPIKE_TH]
        t25 = int(fut.index.get_loc(hit25.index[0]) + 1) if len(hit25) else None
        t30 = int(fut.index.get_loc(hit30.index[0]) + 1) if len(hit30) else None
        max1y = float(vix.iloc[p:p + FWD_1Y].max())
        seg = spx.loc[d0:].iloc[:FWD_1Y]
        dd = float((seg / seg.cummax() - 1.0).min() * 100) if len(seg) > 10 else float("nan")
        print(f"{d0.date()} | {float(vix.iloc[p]):.1f} | "
              f"{t25 if t25 is not None else '아직'}일 | "
              f"{hit25.index[0].date() if len(hit25) else '-'} | "
              f"{t30 if t30 is not None else '아직'}일 | {max1y:.1f} | {dd:+.1f}%")
        if t25 is not None:
            stats.append({"t25": t25, "t30": t30, "max1y": max1y, "dd": dd})
    print()

    if stats:
        st = pd.DataFrame(stats)
        print("── 과거 에피소드 요약 (현재 진행분 제외) ──")
        print(f"다음 스파이크(VIX≥25)까지: 중앙값 {st['t25'].median():.0f}거래일 "
              f"(범위 {st['t25'].min():.0f}~{st['t25'].max():.0f})")
        t30 = st["t30"].dropna()
        if len(t30):
            print(f"VIX≥30 도달: {len(t30)}/{len(st)}회 · 중앙값 {t30.median():.0f}거래일")
        print(f"신호 후 12개월 내 최대 VIX 중앙값 {st['max1y'].median():.1f}")
        print(f"신호 후 12개월 내 SPX 최대 낙폭 중앙값 {st['dd'].median():+.1f}%")
    # 무조건부 비교: 아무 날이나 골랐을 때 다음 ≥25까지 중앙값
    alld = []
    for i in range(0, len(vix) - 1, 21):
        fut = vix.iloc[i + 1:]
        hit = fut[fut >= SPIKE_TH]
        if len(hit):
            alld.append(int(fut.index.get_loc(hit.index[0]) + 1))
    if alld:
        print(f"(비교) 아무 날 기준 다음 스파이크까지 중앙값: {pd.Series(alld).median():.0f}거래일")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
