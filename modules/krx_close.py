import os
import requests
import yfinance as yf
from datetime import datetime, date
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')


def _last_and_pct(symbol: str) -> tuple[float | None, float | None]:
    try:
        df = yf.Ticker(symbol).history(period='5d', interval='1d', auto_adjust=True)
        df = df['Close'].dropna()
        if len(df) < 2:
            return None, None
        prev = float(df.iloc[-2])
        last = float(df.iloc[-1])
        pct = round((last - prev) / prev * 100, 2)
        return round(last, 2), pct
    except Exception:
        return None, None


def _fetch_breadth(today: str) -> dict:
    """pykrx로 KOSPI 상승/하락/보합 및 외국인 순매수."""
    try:
        from pykrx import stock as pkrx
        df = pkrx.get_market_trading_value_by_date(today, today, 'KOSPI')
        foreign_net = None
        if not df.empty and '외국인합계' in df.columns:
            foreign_net = int(df['외국인합계'].iloc[-1] / 1e8)  # 억원

        df2 = pkrx.get_market_price_change_by_ticker(today, today, market='KOSPI')
        up = dn = flat = 0
        if not df2.empty and '등락률' in df2.columns:
            up   = int((df2['등락률'] > 0).sum())
            dn   = int((df2['등락률'] < 0).sum())
            flat = int((df2['등락률'] == 0).sum())
        return {'up': up, 'dn': dn, 'flat': flat, 'foreign_net': foreign_net}
    except Exception:
        return {}


def fetch_krx_snapshot() -> dict:
    today = datetime.now(KST).strftime('%Y%m%d')
    kospi_price, kospi_pct   = _last_and_pct('^KS11')
    kosdaq_price, kosdaq_pct = _last_and_pct('^KQ11')
    _, usd_krw_pct = _last_and_pct('KRW=X')

    try:
        df = yf.Ticker('KRW=X').history(period='5d', interval='1d', auto_adjust=True)
        series = df['Close'].dropna()
        usd_krw = float(series.iloc[-1]) if not series.empty else None
    except Exception:
        usd_krw = None

    breadth = _fetch_breadth(today)
    return {
        'kospi_price':  kospi_price,
        'kospi_pct':    kospi_pct,
        'kosdaq_price': kosdaq_price,
        'kosdaq_pct':   kosdaq_pct,
        'usd_krw':      usd_krw,
        'usd_krw_pct':  usd_krw_pct,
        'breadth':      breadth,
        'as_of': datetime.now(KST).strftime('%Y-%m-%d %H:%M'),
    }


def _evaluate(s: dict) -> str:
    kospi  = s.get('kospi_pct')  or 0
    kosdaq = s.get('kosdaq_pct') or 0
    avg = (kospi + kosdaq) / 2
    if avg >= 1:  return '상승'
    if avg <= -1: return '하락'
    return '혼조'


def build_message(s: dict) -> str:
    def fp(v):
        if v is None: return 'N/A'
        icon = '🔴' if v < -1 else ('🟡' if v < 0 else '🟢')
        return f"{v:+.2f}% {icon}"

    def fkrw(v, pct):
        if v is None: return 'N/A'
        icon = '🔴' if v > 1430 else ('🟡' if v > 1380 else '🟢')
        pct_str = f" ({pct:+.2f}%)" if pct is not None else ''
        return f"{v:,.1f}원{pct_str} {icon}"

    b = s.get('breadth', {})
    breadth_line = ''
    if b.get('up') or b.get('dn'):
        breadth_line = f"  상승 {b['up']}  하락 {b['dn']}  보합 {b.get('flat', 0)}\n"

    foreign_line = ''
    fn = b.get('foreign_net')
    if fn is not None:
        fn_icon = '🔴' if fn < -2000 else ('🟡' if fn < 0 else '🟢')
        fn_str = f"{fn:+,}억" if fn != 0 else "0억"
        foreign_line = f"  외국인 순매수  {fn_str} {fn_icon}\n"

    status = _evaluate(s)
    header_icon = {'상승': '📈', '하락': '📉', '혼조': '📊'}[status]
    action = {
        '상승': '강세 유지 · 추세 추종 유효',
        '하락': '리스크 관리 · 관망 고려',
        '혼조': '종목 선별 · 관망 유지',
    }[status]

    lines = [
        f"<b>{header_icon} 한국 시장 마감  {s['as_of']}</b>",
        "",
        "<b>🇰🇷 지수</b>",
    ]
    if s.get('kospi_price'):
        lines.append(f"  KOSPI    {s['kospi_price']:,.2f}  {fp(s.get('kospi_pct'))}")
    if s.get('kosdaq_price'):
        lines.append(f"  KOSDAQ   {s['kosdaq_price']:,.2f}  {fp(s.get('kosdaq_pct'))}")

    lines += ["", "<b>💵 환율</b>",
              f"  원/달러    {fkrw(s.get('usd_krw'), s.get('usd_krw_pct'))}"]

    if breadth_line or foreign_line:
        lines += ["", "<b>📊 수급</b>"]
        if breadth_line:
            lines.append(breadth_line.rstrip())
        if foreign_line:
            lines.append(foreign_line.rstrip())

    lines += ["", f"<b>{header_icon} {status}세  →  {action}</b>"]
    return '\n'.join(lines)


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


def run_krx_close():
    snapshot = fetch_krx_snapshot()
    message  = build_message(snapshot)
    ok = send_telegram(message)
    if ok:
        print(f"[{snapshot['as_of']}] 한국장 마감 요약 발송 완료 — {_evaluate(snapshot)}세")
    return message
