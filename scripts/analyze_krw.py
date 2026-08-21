"""원/달러 급락(원화 급강세) 역사 분석 — 일회성 애드혹 스크립트.

FRED DEXKOUS(1981~, 일별)와 yfinance KRW=X(최신 구간)를 이어 붙여,
"지금과 같은 속도의 하락"이 과거 언제 있었고 그 뒤 반등이 언제 왔는지 계산한다.
출력은 stdout(Actions 로그 회수용). 저장소에는 아무것도 쓰지 않는다.
"""

from __future__ import annotations

import io
import sys
import urllib.request

import pandas as pd

WINDOW = 60  # "하락 속도" 측정 창 (거래일 ≈ 3개월)
EPISODE_GAP = 120  # 신호일이 이 간격(거래일) 이상 떨어지면 다른 에피소드
FWD = (21, 63, 126, 252)  # 반등 관측 전방 창 (≈1/3/6/12개월)
TROUGH_SCAN = 250  # 신호일 이후 저점 탐색 범위 (거래일)


def load_fred() -> pd.Series:
    """FRED DEXKOUS (원/달러, 1981~). 결측 '.' 제거."""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS"
    raw = urllib.request.urlopen(url, timeout=60).read().decode()
    df = pd.read_csv(io.StringIO(raw))
    df.columns = ["date", "krw"]
    df["krw"] = pd.to_numeric(df["krw"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    return df.dropna().set_index("date")["krw"]


def load_yahoo_tail() -> pd.Series | None:
    """야후 KRW=X 최근 구간 (FRED의 며칠 지연 보완). 실패해도 치명적이지 않다."""
    try:
        import yfinance as yf

        raw = yf.download("KRW=X", period="3mo", interval="1d",
                          auto_adjust=False, progress=False)
        if raw is None or raw.empty:
            return None
        close = raw["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close.index = pd.to_datetime(close.index).tz_localize(None)
        return close.dropna()
    except Exception as exc:  # noqa: BLE001
        print(f"(야후 보완 실패 — FRED만 사용: {exc})", file=sys.stderr)
        return None


def main() -> int:
    s = load_fred()
    tail = load_yahoo_tail()
    if tail is not None:
        extra = tail[tail.index > s.index[-1]]
        if not extra.empty:
            s = pd.concat([s, extra])
    s = s.sort_index()
    s = s[~s.index.duplicated(keep="last")]

    chg = s.pct_change(WINDOW) * 100  # 60거래일 변화율 (%)
    cur = float(chg.iloc[-1])
    cur_date = s.index[-1].date()
    pct_rank = float((chg.dropna() <= cur).mean() * 100)

    print(f"데이터: {s.index[0].date()} ~ {cur_date} ({len(s):,}일)")
    print(f"현재 환율 {s.iloc[-1]:,.1f}원 · 최근 {WINDOW}거래일 변화 {cur:+.2f}%")
    print(f"이 속도는 전체 역사에서 하위 {pct_rank:.1f}% (작을수록 드문 원화 강세 속도)")
    print(f"52주 고점 대비 {float(s.iloc[-1] / s.tail(252).max() - 1) * 100:+.2f}%")
    print()

    # 지금 이상의 속도로 떨어졌던 날들 → 에피소드로 묶기
    signal_dates = chg.index[chg <= cur]
    positions = s.index.get_indexer(signal_dates)
    episodes: list[int] = []  # 각 에피소드의 첫 신호일 위치
    prev = None
    for p in positions:
        if prev is None or p - prev > EPISODE_GAP:
            episodes.append(int(p))
        prev = int(p)

    print(f"동급 이상 급락 에피소드: {len(episodes)}회 (현재 진행분 포함 여부는 마지막 행)")
    print()
    header = ["신호 시작일", "환율", "이후 저점까지", "저점 깊이"] + [f"+{f}일" for f in FWD]
    print(" | ".join(header))
    rows_for_stats: list[dict] = []
    for p in episodes:
        seg = s.iloc[p : p + TROUGH_SCAN + 1]
        trough_pos = int(seg.values.argmin())
        trough_depth = float(seg.iloc[trough_pos] / s.iloc[p] - 1) * 100
        fwd_vals: dict[int, float] = {}
        cells = [
            str(s.index[p].date()),
            f"{s.iloc[p]:,.0f}",
            f"{trough_pos}일",
            f"{trough_depth:+.1f}%",
        ]
        for f in FWD:
            if p + f < len(s):
                v = float(s.iloc[p + f] / s.iloc[p] - 1) * 100
                fwd_vals[f] = v
                cells.append(f"{v:+.1f}%")
            else:
                cells.append("-")
        print(" | ".join(cells))
        if p + FWD[0] < len(s):  # 미래가 있는 에피소드만 통계에
            rows_for_stats.append(
                {"trough_days": trough_pos, "depth": trough_depth, **fwd_vals}
            )
    print()

    if rows_for_stats:
        st = pd.DataFrame(rows_for_stats)
        print("── 과거 에피소드 요약 (현재 진행분 제외 가능성 있음) ──")
        print(f"저점 도달까지 중앙값: {st['trough_days'].median():.0f}거래일 "
              f"(범위 {st['trough_days'].min():.0f}~{st['trough_days'].max():.0f})")
        print(f"추가 하락 깊이 중앙값: {st['depth'].median():+.1f}%")
        for f in FWD:
            if f in st.columns:
                col = st[f].dropna()
                up = float((col > 0).mean() * 100)
                print(f"신호 후 {f}거래일 뒤 환율 변화: 중앙값 {col.median():+.1f}% · "
                      f"반등(상승) 비율 {up:.0f}% (표본 {len(col)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
