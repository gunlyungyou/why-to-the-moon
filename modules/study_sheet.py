import os
import json
import requests
import anthropic
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
_HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

RSS_FEEDS = [
    ('경제', 'https://www.yna.co.kr/rss/economy.xml'),
    ('한경경제', 'https://www.hankyung.com/feed/economy'),
    ('한경증권', 'https://www.hankyung.com/feed/finance'),
]


# ── 데이터 수집 ──────────────────────────────────────────────

def _get_top_movers(today: str) -> list[dict]:
    ETF_KEYWORDS = ['ETF', 'KODEX', 'TIGER', 'KINDEX', 'ARIRANG', 'HANARO', 'KOSEF', 'KBSTAR', 'SOL', 'ACE', '레버리지', '인버스']
    results = []

    try:
        from bs4 import BeautifulSoup
        for sise_type in ['rise', 'fall']:
            url = f'https://finance.naver.com/sise/sise_{sise_type}.naver'
            r = requests.get(url, headers=_HEADERS, timeout=10)
            soup = BeautifulSoup(r.text, 'lxml')
            for row in soup.select('table.type_2 tr'):
                cols = row.select('td')
                if len(cols) < 6:
                    continue
                name = cols[1].get_text(strip=True)
                if not name or any(k in name for k in ETF_KEYWORDS):
                    continue
                pct_text = cols[4].get_text(strip=True).replace('%', '').replace('+', '').replace(',', '')
                vol_text = cols[5].get_text(strip=True).replace(',', '')
                price_text = cols[2].get_text(strip=True).replace(',', '')
                # ticker from link
                a_tag = cols[1].find('a')
                ticker = ''
                if a_tag and 'code=' in a_tag.get('href', ''):
                    ticker = a_tag['href'].split('code=')[-1].strip()
                try:
                    pct    = float(pct_text)
                    volume = int(vol_text)
                    close  = int(price_text)
                    results.append({'ticker': ticker, 'name': name, 'pct': pct, 'volume': volume, 'close': close})
                except Exception:
                    continue
    except Exception as e:
        print(f"[movers] {e}")

    results.sort(key=lambda x: abs(x['pct']) * x['volume'], reverse=True)
    return results[:15]


def _get_today_news() -> list[str]:
    today = datetime.now(KST).date()
    titles = []
    for _, url in RSS_FEEDS:
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item'):
                pub_str = item.findtext('pubDate') or ''
                try:
                    pub = parsedate_to_datetime(pub_str).astimezone(KST).date()
                except Exception:
                    continue
                if pub == today:
                    titles.append((item.findtext('title') or '').strip())
        except Exception:
            continue
    return list(dict.fromkeys(titles))  # 중복 제거


def _get_investor_data(ticker: str, today: str) -> dict:
    try:
        from pykrx import stock as pkrx
        df = pkrx.get_market_net_purchases_of_equities_by_ticker(today, today, market='KOSPI')
        if df.empty or ticker not in df.index:
            return {}
        row = df.loc[ticker]
        cols = row.index.tolist()
        foreign = int(row.iloc[cols.index('외국인합계')] / 1e8) if '외국인합계' in cols else None
        inst    = int(row.iloc[cols.index('기관합계')]   / 1e8) if '기관합계'   in cols else None
        retail  = int(row.iloc[cols.index('개인')]       / 1e8) if '개인'       in cols else None
        return {'foreign': foreign, 'institution': inst, 'retail': retail}
    except Exception as e:
        print(f"[investor] {e}")
        return {}


# ── Claude로 종목 선정 ───────────────────────────────────────

def _select_stock(movers: list[dict], news: list[str]) -> dict:
    if not movers:
        return {}

    client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

    movers_text = '\n'.join(
        f"- {m['name']} ({m['ticker']}): {m['pct']:+.2f}%, 거래량 {m['volume']:,}주"
        for m in movers
    )
    news_text = '\n'.join(f"- {t}" for t in news[:30])

    prompt = f"""오늘 한국 주식 시장 데이터입니다.

급등락 종목 (등락률 × 거래량 순):
{movers_text}

오늘 주요 뉴스:
{news_text}

주식 초보자를 위한 학습 과제로 가장 적합한 종목 하나를 선택하세요.
기준: 뉴스에 언급되거나 시장 전체와 다른 독립적인 이유가 있어서 "왜 이렇게 움직였나?"를 스스로 조사해 답할 수 있는 종목.

JSON만 반환하세요 (설명 없이):
{{"ticker": "종목코드", "name": "종목명", "hint": "어떤 방향에서 이유를 찾아야 할지 방향만 한 줄 (정답 아님, 힌트)"}}"""

    try:
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{'role': 'user', 'content': prompt}]
        )
        raw = resp.content[0].text.strip()
        # 코드블록 제거
        raw = raw.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw)
        for m in movers:
            if m['ticker'] == data.get('ticker') or m['name'] == data.get('name'):
                m['hint'] = data.get('hint', '')
                return m
    except Exception as e:
        print(f"[claude] {e}")

    movers[0]['hint'] = ''
    return movers[0]


# ── 학습지 생성 ──────────────────────────────────────────────

def build_worksheet(stock: dict, investor: dict) -> str:
    name   = stock['name']
    ticker = stock['ticker']
    pct    = stock['pct']
    close  = stock['close']
    volume = stock['volume']
    hint   = stock.get('hint', '')
    icon   = '📈' if pct > 0 else '📉'
    direction = '올랐을' if pct > 0 else '내렸을'

    def investor_line(label, val):
        if val is None:
            return f"   {label}: 직접 확인"
        sign = '순매수 🟢' if val > 0 else '순매도 🔴'
        return f"   {label}: {sign} ({val:+,}억원)"

    lines = [
        f"<b>📚 오늘의 학습지  {datetime.now(KST).strftime('%Y-%m-%d')}</b>",
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"<b>{icon} {name} ({ticker})</b>",
        f"종가  <b>{close:,}원</b>  {pct:+.2f}%",
        f"거래량  {volume:,}주",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"오늘 {name}이 왜 {direction}까요?",
        "아래 질문을 순서대로 채우면 스스로 답이 나옵니다.",
        "",
        "── 1단계: 시장 맥락 ──",
        "",
        "① 오늘 코스피·코스닥은 어떻게 움직였나요?",
        "→ ",
        "",
        f"② {name}의 등락이 시장 전체와 같은 방향인가요?",
        "→ □ 같은 방향  □ 반대  □ 같은 방향이지만 훨씬 크게",
        "",
        f"③ ②의 답을 근거로, 오늘 {name}의 움직임은",
        "→ □ 시장 흐름 때문  □ 종목 자체 이유  □ 둘 다",
        "",
        "── 2단계: 재료(뉴스) ──",
        "",
        f"④ 오늘 {name} 관련 뉴스가 있었나요?",
        f"   (네이버 증권 → {name} → 뉴스 탭)",
        "→ ",
        "",
        "⑤ 그 뉴스가 주가에 미친 영향은 호재인가요, 악재인가요?",
        "   왜 그렇게 판단했나요?",
        "→ ",
        "",
        "── 3단계: 거래량 ──",
        "",
        f"⑥ 오늘 거래량 {volume:,}주는 평소 대비 많은가요?",
        "   (네이버 증권 → 차트 → 하단 거래량 막대 비교)",
        "→ □ 많다  □ 비슷  □ 적다",
        "",
        f"⑦ 주가가 {direction}때 거래량이 많다면 어떤 의미일까요?",
        "→ ",
        "",
        "── 4단계: 수급 ──",
        "",
        "⑧ 외국인·기관·개인 중 누가 샀고 누가 팔았나요?",
    ]

    if investor:
        lines.append(investor_line('외국인', investor.get('foreign')))
        lines.append(investor_line('기관  ', investor.get('institution')))
        lines.append(investor_line('개인  ', investor.get('retail')))
    else:
        lines += [
            "   (네이버 증권 → 투자자별 매매 탭에서 확인)",
            "→ 외국인: ___  기관: ___  개인: ___",
        ]

    lines += [
        "",
        "⑨ 수급을 보고 주가 움직임이 납득되나요?",
        "→ □ 납득된다  □ 여전히 모르겠다",
        "   이유: ",
        "",
        "── 5단계: 나의 결론 ──",
        "",
        f"⑩ 오늘 {name}이 {pct:+.2f}%한 이유를 3줄로 정리하세요.",
        "   (시장 흐름 + 뉴스 재료 + 수급을 모두 담아서)",
        "→ ",
        "   ",
        "   ",
        "",
        f"⑪ 내일 이 종목에 진입하려면 어떤 조건이 갖춰져야 할까요?",
        "→ ",
        "",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if hint:
        lines += [f"💡 힌트: {hint}", ""]

    lines += [
        f"🔍 <b>참고 경로</b>",
        f"네이버 증권 → '{name}' 검색",
        "→ 뉴스 / 투자자별 매매 / 차트 탭",
    ]

    return '\n'.join(lines)


# ── 발송 ────────────────────────────────────────────────────

def _send_telegram(message: str):
    token    = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_ids = [c.strip() for c in os.environ.get('TELEGRAM_CHAT_ID', '').split(',') if c.strip()]
    if not token or not chat_ids:
        print(message)
        return
    for chat_id in chat_ids:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML',
                  'disable_web_page_preview': True},
            timeout=10,
        )


def run_study_sheet():
    today = datetime.now(KST).strftime('%Y%m%d')

    print("[1/4] 오늘 급등락 종목 수집 중...")
    movers = _get_top_movers(today)
    if not movers:
        print("데이터 없음 (장 휴장 또는 pykrx 오류)")
        return

    print(f"[2/4] 오늘 뉴스 수집 중... ({len(movers)}개 종목 후보)")
    news = _get_today_news()

    print("[3/4] Claude가 종목 선정 중...")
    stock = _select_stock(movers, news)
    if not stock:
        return
    print(f"      → {stock['name']} ({stock['pct']:+.2f}%)")

    print("[4/4] 수급 데이터 수집 중...")
    investor = _get_investor_data(stock['ticker'], today)

    message = build_worksheet(stock, investor)
    _send_telegram(message)
    print(f"발송 완료 — {stock['name']} {stock['pct']:+.2f}%")
