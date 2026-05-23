import time
import requests
from bs4 import BeautifulSoup

NAVER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://finance.naver.com',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}


def get_naver_news(ticker: str, ticker_name: str = '', n: int = 10) -> list[dict]:
    """네이버 금융 종목 뉴스에서 최신 n건 수집."""
    results: list[dict] = []
    page = 1

    while len(results) < n and page <= 3:
        url = f"https://finance.naver.com/item/news_news.naver?code={ticker}&page={page}"
        resp = requests.get(url, headers=NAVER_HEADERS, timeout=10)
        resp.encoding = 'euc-kr'
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 메인 기사만 수집 (relation_tit 클래스 행)
        for row in soup.select('tr.relation_tit, tr.first'):
            title_el = row.select_one('td.title a.tit')
            source_el = row.select_one('td.info')
            date_el = row.select_one('td.date')

            if not title_el or not date_el:
                continue

            title = title_el.text.strip()
            if not title:
                continue

            href = title_el.get('href', '')
            full_url = f"https://finance.naver.com{href}" if href.startswith('/') else href

            results.append({
                'title': title,
                'source': source_el.text.strip() if source_el else '',
                'time': date_el.text.strip(),
                'url': full_url,
            })

            if len(results) >= n:
                break

        page += 1
        if len(results) < n and page <= 3:
            time.sleep(0.5)  # robots.txt 준수

    return results[:n]
