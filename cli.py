#!/usr/bin/env python3
"""Phase 1 MVP — CLI로 종목명을 입력받아 주가 등락 원인을 분석한다."""

import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

from modules.stock import get_ticker_code, get_price_info
from modules.news import get_naver_news
from modules.analyzer import explain_price_movement


def fmt_price(val) -> str:
    return f"{val:,}원" if isinstance(val, int) else str(val or 'N/A')


def main():
    if len(sys.argv) > 1:
        ticker_name = ' '.join(sys.argv[1:])
    else:
        ticker_name = input("종목명 입력 (예: 삼성전자): ").strip()

    if not ticker_name:
        print("종목명을 입력하세요.")
        sys.exit(1)

    print(f"\n[1/3] {ticker_name} 주가 데이터 수집 중...")
    ticker = get_ticker_code(ticker_name)
    price = get_price_info(ticker)

    name = price.get('ticker_name') or ticker_name
    sign = price.get('change_sign', '')
    rate = price.get('change_rate') or 0
    current = price.get('current_price')
    open_p = price.get('open_price')

    print(f"  티커  : {ticker} ({name})")
    print(f"  시가  : {fmt_price(open_p)}")
    print(f"  현재가: {fmt_price(current)}  ({price.get('as_of')} 기준)")
    print(f"  등락률: {sign}{rate}%")

    print(f"\n[2/3] 네이버 금융 뉴스 수집 중...")
    news = get_naver_news(ticker, ticker_name, n=10)
    print(f"  {len(news)}건 수집")
    for item in news[:5]:
        print(f"  · [{item.get('time', '')}] {item.get('title', '')}")
    if len(news) > 5:
        print(f"  ... 외 {len(news) - 5}건")

    print(f"\n[3/3] Claude AI 분석 중...")
    analysis = explain_price_movement(ticker_name, price, news)

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  {name} ({ticker})  {sign}{rate}%")
    print(f"  시가 {fmt_price(open_p)} → 현재 {fmt_price(current)}  ({price.get('as_of')} 기준)")
    print(sep)
    print("\n[AI 분석]")
    print(analysis)
    print("\n[참고 뉴스]")
    for item in news:
        print(f"· [{item.get('time', '')}] {item.get('title', '')}  — {item.get('source', '')}")
    print(sep)


if __name__ == '__main__':
    main()
