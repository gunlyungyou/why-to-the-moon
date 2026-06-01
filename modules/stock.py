import re
import time
import requests
import pandas as pd
import yfinance as yf
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta
import FinanceDataReader as fdr

NAVER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://finance.naver.com',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}

# FDR 심볼 → yfinance 심볼
_FDR_TO_YF: dict[str, str] = {
    'NASDAQ': '^IXIC',
    'SP500': '^GSPC',
    'DJI': '^DJI',
    '^N225': '^N225',
    '^HSI': '^HSI',
    'SSE': '000001.SS',
    '^GDAXI': '^GDAXI',
    '^FTSE': '^FTSE',
}

# 통화 → 시장 타임존
_CURRENCY_TZ: dict[str, str] = {
    'KRW': 'Asia/Seoul',
    'JPY': 'Asia/Tokyo',
    'USD': 'America/New_York',
    'HKD': 'Asia/Hong_Kong',
    'CNY': 'Asia/Shanghai',
    'EUR': 'Europe/Berlin',
    'GBP': 'Europe/London',
}

# 한국어 입력 → (FDR 심볼, 표시명, 통화)
_OVERSEAS_INDEX_MAP: dict[str, tuple[str, str, str]] = {
    # 미국
    '나스닥': ('NASDAQ', '나스닥', 'USD'),
    'nasdaq': ('NASDAQ', '나스닥', 'USD'),
    's&p500': ('SP500', 'S&P500', 'USD'),
    'sp500': ('SP500', 'S&P500', 'USD'),
    '에스앤피': ('SP500', 'S&P500', 'USD'),
    '다우': ('DJI', '다우존스', 'USD'),
    '다우존스': ('DJI', '다우존스', 'USD'),
    'dow': ('DJI', '다우존스', 'USD'),
    # 일본
    '니케이': ('^N225', '니케이225', 'JPY'),
    '니케이225': ('^N225', '니케이225', 'JPY'),
    'nikkei': ('^N225', '니케이225', 'JPY'),
    # 홍콩
    '항셍': ('^HSI', '항셍지수', 'HKD'),
    '항생': ('^HSI', '항셍지수', 'HKD'),
    'hsi': ('^HSI', '항셍지수', 'HKD'),
    # 중국
    '상해': ('SSE', '상해종합', 'CNY'),
    '상해종합': ('SSE', '상해종합', 'CNY'),
    # 유럽
    '독일': ('^GDAXI', 'DAX', 'EUR'),
    'dax': ('^GDAXI', 'DAX', 'EUR'),
    '영국': ('^FTSE', 'FTSE100', 'GBP'),
    'ftse': ('^FTSE', 'FTSE100', 'GBP'),
}

# 세션당 한 번만 다운로드
_listing_cache: dict | None = None


def _get_listing() -> dict:
    global _listing_cache
    if _listing_cache is None:
        df = fdr.StockListing('KRX')
        _listing_cache = df.set_index('Code').to_dict(orient='index')
    return _listing_cache


def _lookup_overseas(name: str) -> tuple[str, str, str] | None:
    return _OVERSEAS_INDEX_MAP.get(name.lower().strip().replace(' ', ''))


def get_ticker_code(name: str) -> str:
    """종목명 → 티커. 해외 지수면 FDR 심볼, KRX 종목이면 6자리 코드."""
    if re.match(r'^\d{6}$', name):
        return name

    overseas = _lookup_overseas(name)
    if overseas:
        return overseas[0]  # FDR 심볼

    listing = _get_listing()
    for code, row in listing.items():
        if row.get('Name') == name:
            return code

    raise ValueError(
        f"종목을 찾을 수 없습니다: '{name}'\n"
        "국내 종목은 정확한 종목명(예: 삼성전자) 또는 6자리 코드,\n"
        "해외 지수는 '나스닥', '니케이', 'S&P500', '다우존스', '항셍' 등으로 입력하세요."
    )


def get_price_info(ticker: str) -> dict:
    overseas = next(
        (v for k, v in _OVERSEAS_INDEX_MAP.items() if v[0] == ticker),
        None,
    )
    if overseas:
        return _get_index_price_info(*overseas)
    return _get_stock_price_info(ticker)


def _get_stock_price_info(ticker: str) -> dict:
    today = date.today().strftime('%Y-%m-%d')
    listing = _get_listing()
    row = listing.get(ticker, {})
    open_price = int(row['Open']) if row.get('Open') else None
    high_price = int(row['High']) if row.get('High') else None
    low_price = int(row['Low']) if row.get('Low') else None
    current_price = int(row['Close']) if row.get('Close') else None
    volume = int(row['Volume']) if row.get('Volume') else None
    ticker_name = row.get('Name', '')

    if not current_price:
        try:
            df = fdr.DataReader(ticker, today, today)
            if not df.empty:
                r = df.iloc[-1]
                open_price = open_price or int(r['Open'])
                high_price = high_price or int(r['High'])
                low_price = low_price or int(r['Low'])
                current_price = int(r['Close'])
                volume = volume or int(r['Volume'])
        except Exception:
            pass

    change_rate = None
    change_sign = ''
    change_amount = None
    if current_price and open_price and open_price > 0:
        diff = current_price - open_price
        change_rate = round(abs(diff) / open_price * 100, 2)
        change_sign = '+' if diff >= 0 else '-'
        change_amount = abs(diff)

    return {
        'ticker': ticker,
        'ticker_name': ticker_name,
        'current_price': current_price,
        'open_price': open_price,
        'high_price': high_price,
        'low_price': low_price,
        'volume': volume,
        'change_rate': change_rate,
        'change_sign': change_sign,
        'change_amount': change_amount,
        'as_of': datetime.now().strftime('%H:%M'),
        'currency': 'KRW',
        'is_index': False,
    }


def _get_index_price_info(symbol: str, display_name: str, currency: str) -> dict:
    start = (date.today() - timedelta(days=10)).strftime('%Y-%m-%d')
    end = date.today().strftime('%Y-%m-%d')

    df = fdr.DataReader(symbol, start, end)
    if df.empty:
        raise ValueError(f"데이터를 가져올 수 없습니다: {display_name} ({symbol})")

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else None

    def safe_float(val):
        return float(val) if val is not None and not pd.isna(val) else None

    current_price = safe_float(latest.get('Close'))
    open_price = safe_float(latest.get('Open'))
    prev_close = safe_float(prev['Close']) if prev is not None else None

    change_rate = None
    change_sign = ''
    reference = prev_close or open_price
    if current_price and reference and reference > 0:
        diff = current_price - reference
        change_rate = round(abs(diff) / reference * 100, 2)
        change_sign = '+' if diff >= 0 else '-'

    as_of = df.index[-1].strftime('%Y-%m-%d') if hasattr(df.index[-1], 'strftime') else str(df.index[-1])

    return {
        'ticker': symbol,
        'ticker_name': display_name,
        'current_price': current_price,
        'open_price': open_price,
        'high_price': safe_float(latest.get('High')),
        'low_price': safe_float(latest.get('Low')),
        'volume': None,
        'change_rate': change_rate,
        'change_sign': change_sign,
        'change_amount': abs(current_price - reference) if current_price and reference else None,
        'as_of': as_of,
        'currency': currency,
        'is_index': True,
    }


def describe_chart_pattern(chart_data: list[dict], currency: str = 'KRW') -> str:
    """5분봉 데이터를 Claude가 읽을 수 있는 장중 흐름 텍스트로 변환."""
    if not chart_data or len(chart_data) < 3:
        return ""

    from zoneinfo import ZoneInfo
    from datetime import datetime

    tz = ZoneInfo(_CURRENCY_TZ.get(currency, 'Asia/Seoul'))

    def fmt_t(ts):
        return datetime.fromtimestamp(ts, tz=tz).strftime('%H:%M')

    open_p = chart_data[0]['open']
    def pct(p):
        return (p - open_p) / open_p * 100 if open_p else 0

    n = len(chart_data)
    pcts = [pct(c['close']) for c in chart_data]

    max_c = max(chart_data, key=lambda c: c['high'])
    min_c = min(chart_data, key=lambda c: c['low'])

    # 시간대별 누적 변동 (4개 체크포인트)
    checkpoints = [n // 4, n // 2, 3 * n // 4, n - 1]
    cp_str = ' → '.join(
        f"{fmt_t(chart_data[i]['time'])} {pcts[i]:+.2f}%"
        for i in checkpoints if i < n
    )

    return (
        f"[장중 차트 흐름] {fmt_t(chart_data[0]['time'])} ~ {fmt_t(chart_data[-1]['time'])}\n"
        f"  장중 최고: 시가 대비 {pct(max_c['high']):+.2f}% ({fmt_t(max_c['time'])})\n"
        f"  장중 최저: 시가 대비 {pct(min_c['low']):+.2f}% ({fmt_t(min_c['time'])})\n"
        f"  현재: 시가 대비 {pct(chart_data[-1]['close']):+.2f}%\n"
        f"  누적 변동 추이: {cp_str}"
    )


def is_overseas_index_ticker(ticker: str) -> bool:
    return any(v[0] == ticker for v in _OVERSEAS_INDEX_MAP.values())


def get_market_context(ticker: str, currency: str = 'KRW') -> dict:
    """최근 5거래일 평균 변동률(변동성) + 오늘 시장 지수 수익률 반환."""
    result = {'avg_daily_pct': None, 'market_index_pct': None, 'market_index_name': None}
    today = date.today().strftime('%Y-%m-%d')
    start = (date.today() - timedelta(days=14)).strftime('%Y-%m-%d')

    try:
        if is_overseas_index_ticker(ticker):
            df = fdr.DataReader(ticker, start, today)
        else:
            df = fdr.DataReader(ticker, start, today)

        if len(df) >= 2:
            closes = df['Close'].dropna()
            daily_pcts = closes.pct_change().dropna().abs() * 100
            result['avg_daily_pct'] = round(float(daily_pcts.tail(5).mean()), 2)
    except Exception:
        pass

    if currency == 'KRW' and not is_overseas_index_ticker(ticker):
        try:
            df_kospi = fdr.DataReader('KS11', start, today)
            if len(df_kospi) >= 2:
                latest = float(df_kospi['Close'].iloc[-1])
                prev = float(df_kospi['Close'].iloc[-2])
                result['market_index_pct'] = round((latest - prev) / prev * 100, 2)
                result['market_index_name'] = 'KOSPI'
        except Exception:
            pass

    return result


_popular_cache: list | None = None
_popular_cache_ts: float = 0
_POPULAR_TTL = 600  # 10분


def _get_naver_popular_codes(n: int = 50) -> list[str]:
    """네이버 금융 인기 검색 종목 코드 반환."""
    url = 'https://finance.naver.com/sise/lastsearch2.nhn'
    resp = requests.get(url, headers=NAVER_HEADERS, timeout=6)
    soup = BeautifulSoup(resp.text, 'html.parser')
    table = soup.find('table', class_='type_5')
    if not table:
        return []
    codes = []
    for row in table.find_all('tr'):
        cols = row.find_all('td')
        name_el = cols[1].find('a') if len(cols) > 1 else None
        if not name_el:
            continue
        m = re.search(r'code=(\d{6})', name_el.get('href', ''))
        if m:
            codes.append(m.group(1))
        if len(codes) >= n:
            break
    return codes


def get_surging_popular_stocks(limit: int = 10) -> list[dict]:
    """시가총액 상위 150개 ∩ 네이버 인기 검색 → 오늘 급등 순 정렬 (5분 캐시)."""
    global _popular_cache, _popular_cache_ts

    if _popular_cache is not None and time.time() - _popular_cache_ts < _POPULAR_TTL:
        return _popular_cache[:limit]

    try:
        # 1) 네이버 인기 검색 코드 집합 (최근 7일 많이 오르내린 종목들)
        popular_set = set(_get_naver_popular_codes(50))
        if not popular_set:
            return _popular_cache[:limit] if _popular_cache else []

        # 2) KRX 전체 → KOSPI 시장만 + 시가총액 상위 80개
        #    (KOSDAQ 소형 테마주 제외, 일시적 급등으로 시가총액 부풀어도 못 들어옴)
        listing = _get_listing()
        kospi_stocks = [
            (code, row) for code, row in listing.items()
            if row.get('Market') == 'KOSPI' and (row.get('Marcap') or 0) > 0
        ]
        sorted_by_marcap = sorted(kospi_stocks, key=lambda x: x[1].get('Marcap', 0), reverse=True)

        # 3) 교집합: 인기 검색 AND KOSPI 상위 80개
        candidates_codes = [code for code, _ in sorted_by_marcap[:80] if code in popular_set]

        # 80 안에 5개 미만이면 150까지 확장
        if len(candidates_codes) < 5:
            candidates_codes = [code for code, _ in sorted_by_marcap[:150] if code in popular_set]

        # 4) 후보 목록 구성
        naver_rank = {code: i for i, code in enumerate(candidates_codes)}

        pool = []
        for code in candidates_codes:
            row = listing.get(code, {})
            change_ratio = row.get('ChagesRatio')
            marcap = float(row.get('Marcap') or 0)
            if change_ratio is None:
                continue
            change_ratio = float(change_ratio)
            close = row.get('Close')
            pool.append({
                'rank': 0,
                'name': row.get('Name', ''),
                'code': code,
                'current_price': int(close) if close else None,
                'change_rate': round(abs(change_ratio), 2),
                'change_sign': '+' if change_ratio > 0 else ('-' if change_ratio < 0 else ''),
                '_ratio': change_ratio,
                '_marcap': marcap,
                '_naver_rank': naver_rank.get(code, 999),
            })

        # 상위 5: Naver 인기 순위 순 (오늘 상승 종목 우선)
        by_naver = sorted(pool, key=lambda x: (x['_ratio'] <= 0, x['_naver_rank']))
        top5 = by_naver[:5]
        top5_codes = {c['code'] for c in top5}

        # 하위 5: 나머지 중 시가총액 × 등락률 가중 점수 순
        rest = [c for c in pool if c['code'] not in top5_codes]
        rest.sort(key=lambda x: x['_ratio'] * x['_marcap'], reverse=True)
        next5 = rest[:5]

        candidates = top5 + next5
        for i, c in enumerate(candidates):
            c['rank'] = i + 1
            del c['_ratio'], c['_marcap'], c['_naver_rank']

        _popular_cache = candidates
        _popular_cache_ts = time.time()
        return candidates[:limit]

    except Exception:
        return _popular_cache[:limit] if _popular_cache else []


def get_chart_data(ticker: str, is_index: bool = False) -> list[dict]:
    """5분봉 데이터 반환. 오늘 데이터 없으면 가장 최근 거래일 기준."""
    if is_index:
        yf_symbol = _FDR_TO_YF.get(ticker, ticker)
    else:
        listing = _get_listing()
        market = listing.get(ticker, {}).get('Market', 'KOSPI')
        yf_symbol = ticker + ('.KQ' if market == 'KOSDAQ' else '.KS')

    try:
        tk = yf.Ticker(yf_symbol)
        df = tk.history(period='5d', interval='5m', auto_adjust=True)
        if df.empty:
            return []

        if df.index.tz:
            df.index = df.index.tz_convert('UTC')
        else:
            df.index = df.index.tz_localize('UTC')

        last_date = df.index[-1].date()
        df = df[df.index.date == last_date]

        return [
            {
                'time': int(row.Index.timestamp()),
                'open': round(float(row.Open), 4),
                'high': round(float(row.High), 4),
                'low': round(float(row.Low), 4),
                'close': round(float(row.Close), 4),
            }
            for row in df.itertuples()
            if not any(pd.isna(v) for v in [row.Open, row.High, row.Low, row.Close])
        ]
    except Exception:
        return []
