import os
import json
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
STATE_FILE = '.seen_news.json'

RSS_FEEDS = [
    ('경제', 'https://www.yna.co.kr/rss/economy.xml'),
    ('한경경제', 'https://www.hankyung.com/feed/economy'),
    ('한경증권', 'https://www.hankyung.com/feed/finance'),
]

_HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}


def _load_seen() -> set[str]:
    try:
        with open(STATE_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def _save_seen(seen: set[str]):
    with open(STATE_FILE, 'w') as f:
        json.dump(list(seen)[-1000:], f)


def _parse_feed(url: str) -> list[dict]:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        root = ET.fromstring(resp.content)
        items = []
        for item in root.findall('.//item'):
            guid  = item.findtext('guid') or item.findtext('link') or ''
            title = (item.findtext('title') or '').strip()
            link  = item.findtext('link') or ''
            pub_str = item.findtext('pubDate') or ''
            try:
                pub = parsedate_to_datetime(pub_str)
            except Exception:
                pub = datetime.now(timezone.utc)
            items.append({'id': guid, 'title': title, 'link': link, 'pub': pub})
        return items
    except Exception:
        return []


def _send(token: str, chat_ids: list[str], message: str):
    for chat_id in chat_ids:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
            },
            timeout=10,
        )


def run_news_alert():
    is_first_run = not os.path.exists(STATE_FILE)
    seen = _load_seen()

    seen_titles: set[str] = set()  # 이번 실행 내 제목 중복 제거용

    new_articles: list[dict] = []
    for category, url in RSS_FEEDS:
        for article in _parse_feed(url):
            if article['id'] in seen:
                continue
            seen.add(article['id'])
            if not is_first_run:
                if '[속보]' not in article['title']:
                    continue
                norm = article['title'].replace('[속보]', '').strip()
                if norm in seen_titles:
                    continue
                seen_titles.add(norm)
                article['category'] = category
                new_articles.append(article)

    _save_seen(seen)

    if is_first_run:
        print(f"[뉴스 알림] 초기화 완료 — {len(seen)}건 등록, 다음 실행부터 발송")
        return

    if not new_articles:
        print("[뉴스 알림] 새 기사 없음")
        return

    new_articles.sort(key=lambda x: x['pub'])

    token    = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_ids = [c.strip() for c in os.environ.get('TELEGRAM_CHAT_ID', '').split(',') if c.strip()]

    for article in new_articles:
        kst_time = article['pub'].astimezone(KST).strftime('%H:%M')
        msg = (
            f"<b>📰 [{article['category']}] {kst_time}</b>\n"
            f"{article['title']}\n"
            f"<a href=\"{article['link']}\">기사 보기</a>"
        )
        if token and chat_ids:
            _send(token, chat_ids, msg)
        else:
            print(msg)

    print(f"[뉴스 알림] {len(new_articles)}건 발송")
