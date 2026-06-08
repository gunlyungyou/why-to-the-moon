import numpy as np
import pandas as pd
import FinanceDataReader as fdr
from datetime import date, timedelta


def _load_daily(ticker: str, days: int = 520) -> pd.DataFrame:
    end = date.today().strftime('%Y-%m-%d')
    start = (date.today() - timedelta(days=days + 60)).strftime('%Y-%m-%d')

    # FDR 우선 시도 (로컬/한국 IP 환경)
    try:
        df = fdr.DataReader(ticker, start, end)
        if not df.empty and len(df) >= 30:
            return df.tail(days)
    except Exception:
        pass

    # yfinance 폴백 (해외 서버 환경에서 KRX API 차단 시)
    import yfinance as yf
    for suffix in ['.KS', '.KQ']:
        try:
            df = yf.Ticker(ticker + suffix).history(start=start, end=end, interval='1d', auto_adjust=True)
            if df.empty or len(df) < 30:
                continue
            if df.index.tz:
                df.index = df.index.tz_localize(None)
            return df.tail(days)
        except Exception:
            continue

    raise ValueError("기술적 분석을 위한 데이터가 부족합니다")


def _to_date_str(idx) -> str:
    if hasattr(idx, 'strftime'):
        return idx.strftime('%Y-%m-%d')
    return str(idx)[:10]


def _calc_indicators(df: pd.DataFrame) -> dict:
    close = df['Close'].astype(float)
    high = df['High'].astype(float)
    low = df['Low'].astype(float)
    volume = df['Volume'].astype(float)

    # RSI(14)
    delta = close.diff()
    ag = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    al = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi = (100 - 100 / (1 + ag / al.replace(0, float('nan')))).fillna(50)

    # MACD(12,26,9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_l = ema12 - ema26
    macd_s = macd_l.ewm(span=9, adjust=False).mean()
    macd_hist = macd_l - macd_s

    # Bollinger Bands(20,2)
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_u = ma20 + 2 * std20
    bb_l = ma20 - 2 * std20
    bb_pct = ((close - bb_l) / (bb_u - bb_l).replace(0, float('nan'))).fillna(0.5)

    # MA60
    ma60 = close.rolling(60).mean()
    ma60_v = float(ma60.iloc[-1]) if not pd.isna(ma60.iloc[-1]) else None

    cur = float(close.iloc[-1])
    ma20_v = float(ma20.iloc[-1])
    vol_avg = float(volume.tail(20).mean())
    vol_ratio = float(volume.iloc[-1]) / vol_avg if vol_avg > 0 else 1.0

    def r2(v): return round(float(v), 2) if v is not None else None

    return {
        'close': r2(cur),
        'ma20': r2(ma20_v),
        'ma60': r2(ma60_v),
        'rsi': r2(rsi.iloc[-1]),
        'rsi_prev': r2(rsi.iloc[-2]) if len(rsi) >= 2 else None,
        'macd': round(float(macd_l.iloc[-1]), 4),
        'macd_signal': round(float(macd_s.iloc[-1]), 4),
        'macd_hist': round(float(macd_hist.iloc[-1]), 4),
        'macd_hist_prev': round(float(macd_hist.iloc[-2]), 4) if len(macd_hist) >= 2 else None,
        'bb_upper': r2(bb_u.iloc[-1]),
        'bb_lower': r2(bb_l.iloc[-1]),
        'bb_pct': round(float(bb_pct.iloc[-1]), 3),
        'recent_high_20d': r2(float(high.tail(20).max())),
        'recent_low_20d': r2(float(low.tail(20).min())),
        'vol_ratio': round(vol_ratio, 2),
        'price_vs_ma20': round((cur - ma20_v) / ma20_v * 100, 2) if ma20_v else None,
        'price_vs_ma60': round((cur - ma60_v) / ma60_v * 100, 2) if ma60_v else None,
    }


def _build_candles(df: pd.DataFrame, display_days: int) -> list[dict]:
    result = []
    for idx, row in df.tail(display_days).iterrows():
        o, h, l, c = float(row['Open']), float(row['High']), float(row['Low']), float(row['Close'])
        if any(pd.isna(v) for v in [o, h, l, c]):
            continue
        result.append({
            'time': _to_date_str(idx),
            'open': round(o, 2), 'high': round(h, 2),
            'low': round(l, 2), 'close': round(c, 2),
        })
    return result


def _regression_channel(df: pd.DataFrame, window: int) -> dict:
    data = df.tail(window)
    x = np.arange(len(data), dtype=float)
    y = data['Close'].values.astype(float)
    coeffs = np.polyfit(x, y, 1)
    y_pred = np.polyval(coeffs, x)
    std = float((y - y_pred).std())

    dates = [_to_date_str(idx) for idx in data.index]
    center = [{'time': d, 'value': round(float(v), 2)} for d, v in zip(dates, y_pred)]
    upper  = [{'time': d, 'value': round(float(v + 2 * std), 2)} for d, v in zip(dates, y_pred)]
    lower  = [{'time': d, 'value': round(float(v - 2 * std), 2)} for d, v in zip(dates, y_pred)]

    # 현재가의 채널 내 위치 (0=하단, 1=상단)
    cur = y[-1]
    lo = y_pred[-1] - 2 * std
    hi = y_pred[-1] + 2 * std
    pos = round((cur - lo) / (hi - lo), 3) if std > 0 else 0.5
    pos = max(0.0, min(1.0, pos))

    return {
        'center': center,
        'upper': upper,
        'lower': lower,
        'channel_pos': pos,
        'std': round(std, 2),
    }


def _backtest(df: pd.DataFrame, indicators: dict,
              forward_days: int = 5, min_return: float = 0.02) -> dict:
    close = df['Close'].astype(float)

    # 지표 전체 재계산
    delta = close.diff()
    ag = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    al = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rsi_a = (100 - 100 / (1 + ag / al.replace(0, float('nan')))).fillna(50)

    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_a = ((close - (ma20 - 2 * std20)) / (4 * std20).replace(0, float('nan'))).fillna(0.5)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    mh_a = (ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()

    def rz(r): return 0 if r < 35 else (1 if r < 50 else (2 if r < 65 else 3))
    def bz(b): return 0 if b < 0.3 else (1 if b < 0.7 else 2)
    def mz(h, p): return (1 if h > 0 else 0) * 2 + (1 if h > p else 0)

    cur_rz = rz(indicators['rsi'])
    cur_bz = bz(indicators['bb_pct'])
    cur_mz = mz(indicators['macd_hist'], indicators.get('macd_hist_prev') or 0)

    n = len(close)
    returns = []
    for i in range(30, n - forward_days - 1):
        r, b = float(rsi_a.iloc[i]), float(bb_a.iloc[i])
        h = float(mh_a.iloc[i])
        hp = float(mh_a.iloc[i - 1]) if i > 0 else 0
        if sum([rz(r) == cur_rz, bz(b) == cur_bz, mz(h, hp) == cur_mz]) >= 2:
            entry = float(close.iloc[i])
            future = float(close.iloc[i + forward_days])
            returns.append((future - entry) / entry)

    if len(returns) < 3:
        return {'n_signals': len(returns), 'win_rate': None, 'avg_return': None, 'forward_days': forward_days}

    arr = np.array(returns)
    wins = int((arr >= min_return).sum())
    return {
        'n_signals': len(returns),
        'n_wins': wins,
        'win_rate': round(float(wins / len(returns) * 100), 1),
        'avg_return': round(float(arr.mean() * 100), 2),
        'forward_days': forward_days,
        'min_return_pct': round(min_return * 100, 1),
    }


# ── 공개 API ───────────────────────────────────────────────────────────

def get_technical_indicators(ticker: str) -> dict:
    """기존 advise 흐름 호환용."""
    return _calc_indicators(_load_daily(ticker, days=220))


def get_chart_and_analysis(ticker: str, display_days: int = 120, channel_window: int = 60) -> dict:
    """
    일봉 캔들 + 회귀 채널 + 기술 지표 + 백테스트 승률을 한 번에 반환.
    display_days: 차트에 표시할 캔들 수
    channel_window: 회귀 채널 계산에 쓸 거래일 수 (최근 N일)
    """
    df = _load_daily(ticker, days=520)
    indicators = _calc_indicators(df)
    return {
        'candles': _build_candles(df, display_days),
        'channel': _regression_channel(df, channel_window),
        'indicators': indicators,
        'backtest': _backtest(df, indicators),
    }
