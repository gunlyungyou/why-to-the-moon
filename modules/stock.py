import re
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime
import FinanceDataReader as fdr

NAVER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://finance.naver.com',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}

# 세션당 한 번만 다운로드
_listing_cache: dict | None = None


def _get_listing() -> dict:
    """KRX 전체 종목 목록 (Code→row) - 세션 내 캐시."""
    global _listing_cache
    if _listing_cache is None:
        df = fdr.StockListing('KRX')
        _listing_cache = df.set_index('Code').to_dict(orient='index')
    return _listing_cache


def get_ticker_code(name: str) -> str:
    """종목명 → 6자리 티커 코드. 이미 코드면 그대로 반환."""
    if re.match(r'^\d{6}$', name):
        return name

    listing = _get_listing()
    for code, row in listing.items():
        if row.get('Name') == name:
            return code

    raise ValueError(
        f"종목을 찾을 수 없습니다: '{name}'\n"
        "힌트: 정확한 종목명(예: '삼성전자') 또는 6자리 코드(예: '005930')를 입력하세요."
    )


def get_price_info(ticker: str) -> dict:
    """FinanceDataReader로 오늘 OHLCV 수집 후 장중 등락률(시가 기준) 계산."""
    today = date.today().strftime('%Y-%m-%d')

    # StockListing에서 오늘 데이터 추출
    listing = _get_listing()
    row = listing.get(ticker, {})
    open_price = int(row['Open']) if row.get('Open') else None
    high_price = int(row['High']) if row.get('High') else None
    low_price = int(row['Low']) if row.get('Low') else None
    current_price = int(row['Close']) if row.get('Close') else None
    volume = int(row['Volume']) if row.get('Volume') else None
    ticker_name = row.get('Name', '')

    # DataReader로 보완 (StockListing 데이터가 비어있을 경우)
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

    # 시가 기준 장중 등락률 계산
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
    }
