import os
import requests
import yfinance as yf
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')


def _pct_change(symbol: str) -> float | None:
    try:
        df = yf.Ticker(symbol).history(period='5d', interval='1d', auto_adjust=True)
        if len(df) < 2:
            return None
        prev = float(df['Close'].iloc[-2])
        last = float(df['Close'].iloc[-1])
        return round((last - prev) / prev * 100, 2)
    except Exception:
        return None


def _last_price(symbol: str) -> float | None:
    try:
        df = yf.Ticker(symbol).history(period='2d', interval='1d', auto_adjust=True)
        if df.empty:
            return None
        return float(df['Close'].iloc[-1])
    except Exception:
        return None


def fetch_market_snapshot() -> dict:
    """나스닥·S&P500·VIX·원달러·KOSPI 한 번에 수집."""
    return {
        'nasdaq_pct': _pct_change('^IXIC'),
        'sp500_pct':  _pct_change('^GSPC'),
        'vix':        _last_price('^VIX'),
        'usd_krw':    _last_price('KRW=X'),
        'kospi_pct':  _pct_change('^KS11'),
        'as_of': datetime.now(KST).strftime('%Y-%m-%d %H:%M'),
    }


def evaluate_danger(s: dict) -> str:
    """시장 위험도: 위험 / 주의 / 양호"""
    score = 0
    nasdaq = s.get('nasdaq_pct') or 0
    sp500  = s.get('sp500_pct') or 0
    vix    = s.get('vix') or 0
    krw    = s.get('usd_krw') or 0
    kospi  = s.get('kospi_pct') or 0

    # 미국 지수
    if nasdaq < -3 or sp500 < -3:     score += 3
    elif nasdaq < -1.5 or sp500 < -1.5: score += 1

    # 공포지수
    if vix > 30:   score += 3
    elif vix > 20: score += 1

    # 환율 (원화 약세 = 위험)
    if krw > 1430:   score += 2
    elif krw > 1380: score += 1

    # KOSPI
    if kospi < -2:   score += 2
    elif kospi < -1: score += 1

    if score >= 5: return '위험'
    if score >= 2: return '주의'
    return '양호'


def build_message(s: dict) -> str:
    def fp(v):
        if v is None: return 'N/A'
        icon = '🔴' if v < -2 else ('🟡' if v < -0.5 else '🟢')
        return f"{v:+.2f}% {icon}"

    def fvix(v):
        if v is None: return 'N/A'
        icon = '🔴' if v > 30 else ('🟡' if v > 20 else '🟢')
        return f"{v:.1f} {icon}"

    def fkrw(v):
        if v is None: return 'N/A'
        icon = '🔴' if v > 1430 else ('🟡' if v > 1380 else '🟢')
        return f"{v:,.0f}원 {icon}"

    danger = evaluate_danger(s)
    header = {'위험': '🚨 위험', '주의': '⚠️ 주의', '양호': '✅ 양호'}[danger]
    action = {
        '위험': '신규 진입 자제 · 보유 포지션 점검',
        '주의': '포지션 크기 축소 고려',
        '양호': '정상 매매 가능',
    }[danger]

    return '\n'.join([
        f"<b>📊 시장 경보  {s['as_of']}</b>",
        "",
        "<b>🌏 미국 시장 (전일)</b>",
        f"  나스닥     {fp(s.get('nasdaq_pct'))}",
        f"  S&P500    {fp(s.get('sp500_pct'))}",
        f"  VIX 공포지수  {fvix(s.get('vix'))}",
        "",
        "<b>💵 환율</b>",
        f"  원/달러    {fkrw(s.get('usd_krw'))}",
        "",
        "<b>🇰🇷 KOSPI (전일)</b>",
        f"  등락률     {fp(s.get('kospi_pct'))}",
        "",
        f"<b>{header}  →  {action}</b>",
    ])


def send_telegram(message: str) -> bool:
    token    = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_ids = [c.strip() for c in os.environ.get('TELEGRAM_CHAT_ID', '').split(',') if c.strip()]
    if not token or not chat_ids:
        print("[텔레그램 미설정] 콘솔 출력:\n", message)
        return False
    ok = True
    for chat_id in chat_ids:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
            timeout=10,
        )
        if resp.status_code != 200:
            ok = False
    return ok


def run_alert():
    snapshot = fetch_market_snapshot()
    message  = build_message(snapshot)
    ok = send_telegram(message)
    if ok:
        print(f"[{snapshot['as_of']}] 텔레그램 발송 완료 — {evaluate_danger(snapshot)}")
    return message
