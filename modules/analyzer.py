import os
import json
import re
import anthropic

TRADING_SYSTEM_PROMPT = """당신은 단기 주식 매매(수일~2주) 전문 기술적 분석가입니다. 반드시 한국어로, 반드시 JSON 형식으로만 답변하세요.

주어진 기술적 지표와 뉴스를 분석하고 아래 JSON만 출력하세요 (마크다운 코드블록 없이):

{
  "signal": "매수 고려" | "관망" | "매도 고려",
  "signal_strength": "강" | "중" | "약",
  "summary": "현재 기술적 상황 1~2문장",
  "buy_zone": "XX,XXX원 ~ XX,XXX원 또는 null",
  "target_price": "XX,XXX원 또는 null",
  "stop_loss": "XX,XXX원 또는 null",
  "holding_period": "X~Y일 또는 null",
  "reasons": ["근거 1", "근거 2", "근거 3"],
  "risks": ["리스크 1", "리스크 2"]
}

판단 기준 (단기 기준):
- RSI < 35: 과매도 → 매수 신호
- RSI > 65: 과매수 → 매도 신호
- MACD 히스토그램 음→양 전환: 매수 신호
- MACD 히스토그램 양→음 전환: 매도 신호
- 볼린저밴드 %B < 0.2: 하단 근접 → 반등 가능
- 볼린저밴드 %B > 0.8: 상단 근접 → 과열
- 현재가 MA20 대비 -5% 이하: 지지 구간
- 현재가 MA20 대비 +7% 이상: 저항 구간
- 거래량 1.5배 이상: 신호 강도 상승
- 복수 신호 일치 시 "강", 단일 신호 시 "중", 혼재 시 "약"

buy_zone: 매수 고려 시 이상적 진입 범위 (현재가 ±2~3%), 관망/매도 시 null
target_price: 단기 목표가 (최근 20일 고점 또는 MA20/60 기준), 관망/매도 시 null
stop_loss: 손절 기준가 (최근 20일 저점 또는 볼린저밴드 하단 기준, -3~5%), 매수 고려 시만 필수
holding_period: 예상 보유 기간 (예: "3~7일"), 매수 고려 시만 필수"""

CLAUDE_MODEL = 'claude-sonnet-4-6'

SYSTEM_PROMPT = """당신은 한국 주식 시장 전문가입니다. 반드시 한국어로, 반드시 JSON 형식으로만 답변하세요.

주어진 주가 데이터, 장중 차트 흐름, 뉴스를 분석하고 아래 JSON만 출력하세요 (마크다운 코드블록 없이):

{
  "headline": "하루 흐름 한 줄 요약 (15자 이내, 예: '장 초반 급등 후 오후 횡보')",
  "phases": [
    {
      "label": "구간명",
      "time": "HH:MM~HH:MM",
      "change": "+X.X%",
      "reason": "이 구간의 원인 (30자 이내)"
    }
  ],
  "detail": "전체 흐름 2~3문장 요약"
}

label 선택 규칙 (반드시 준수):
- 사용 가능한 label: 급등 / 상승 / 횡보 / 하락 / 급락 / 반등
- [시장 맥락]에 '최근 5거래일 평균 일일 변동률'이 제공된 경우, 그 값(avg)을 기준으로:
    구간 변동폭 > avg × 1.2  →  급등 또는 급락
    avg × 0.4 ~ avg × 1.2   →  상승 또는 하락
    구간 변동폭 < avg × 0.4  →  횡보
  '반등'은 직전 구간 방향이 역전되는 경우에만 사용
- 맥락 데이터가 없으면 절대적 크기로 판단 (2% 이상 급등/급락, 1~2% 상승/하락, 1% 미만 횡보)

phases 구분 원칙:
- 반드시 2~3개. 핵심 전환점 기준으로만 나눔 (오늘 전체 움직임 대비 의미 없는 소음은 흡수)
- 뉴스·공시가 특정 시간대와 연관되면 해당 phase reason에 반영
- 장중 차트 데이터 없으면 전체 등락을 1개 phase로 표현

detail 작성 원칙:
- 오늘 움직임이 이 종목의 평소 변동성 대비 이례적인지 여부를 반드시 한 문장으로 언급
  예) "SK하이닉스는 평소 일일 변동률이 ±2%대인 고변동 종목으로, 오늘 낙폭은 일반적인 범위 내입니다."
- 불확실한 내용은 '~로 보입니다' 표현"""


def _build_user_message(ticker_name, price_info, news_items, chart_data=None, disclosures=None, market_context=None):
    sign = price_info.get('change_sign', '')
    rate = price_info.get('change_rate') or 0
    direction = '상승' if sign == '+' else ('하락' if sign == '-' else '변동')
    open_p = price_info.get('open_price')
    current_p = price_info.get('current_price')
    as_of = price_info.get('as_of', '현재')

    currency = price_info.get('currency', 'KRW')
    if currency == 'KRW':
        open_str = f"{int(open_p):,}원" if open_p else '알 수 없음'
        current_str = f"{int(current_p):,}원" if current_p else '알 수 없음'
    else:
        open_str = f"{open_p:,.2f} {currency}" if open_p else '알 수 없음'
        current_str = f"{current_p:,.2f} {currency}" if current_p else '알 수 없음'

    news_lines = '\n'.join(
        f"- [{item.get('time', '')}] {item.get('title', '')} ({item.get('source', '')})"
        for item in news_items
    ) or '- 관련 뉴스 없음'

    disclosure_lines = ''
    if disclosures:
        disclosure_lines = '\n공시:\n' + '\n'.join(
            f"- {d.get('title', '')}" for d in disclosures
        )

    chart_section = ''
    if chart_data:
        from modules.stock import describe_chart_pattern
        pattern = describe_chart_pattern(chart_data, currency)
        if pattern:
            chart_section = f'\n\n{pattern}'

    context_section = ''
    if market_context:
        avg_vol = market_context.get('avg_daily_pct')
        mkt_pct = market_context.get('market_index_pct')
        mkt_name = market_context.get('market_index_name')
        parts = []
        if avg_vol is not None:
            parts.append(f"최근 5거래일 평균 일일 변동률: ±{avg_vol:.2f}%")
        if mkt_pct is not None and mkt_name:
            sign_m = '+' if mkt_pct >= 0 else ''
            parts.append(f"오늘 {mkt_name}: {sign_m}{mkt_pct:.2f}%")
        if parts:
            context_section = '\n\n[시장 맥락]\n' + '\n'.join(parts)

    return (
        f"{ticker_name}이(가) 오늘 시가({open_str})부터 "
        f"{as_of} 현재({current_str})까지 {sign}{rate}% {direction}했습니다."
        f"{chart_section}"
        f"{context_section}\n\n"
        f"관련 뉴스:\n{news_lines}"
        f"{disclosure_lines}\n\n"
        f"장중 차트 흐름과 뉴스를 바탕으로 구간별 원인을 분석해 주세요."
    )


def explain_price_movement(ticker_name, price_info, news_items, chart_data=None, disclosures=None, market_context=None) -> dict:
    user_message = _build_user_message(ticker_name, price_info, news_items, chart_data, disclosures, market_context)
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': user_message}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {'headline': '분석 완료', 'phases': [], 'detail': raw}


def advise_trading(ticker_name: str, price_info: dict, indicators: dict,
                   backtest: dict, news_items: list) -> dict:
    cur = price_info.get('current_price', 0)
    currency = price_info.get('currency', 'KRW')

    def fp(v):
        if v is None:
            return 'N/A'
        if currency == 'KRW':
            return f"{int(v):,}원"
        return f"{v:,.2f} {currency}"

    ind = indicators
    news_lines = '\n'.join(
        f"- [{item.get('time', '')}] {item.get('title', '')}"
        for item in news_items[:5]
    ) or '- 관련 뉴스 없음'

    ma60_line = ''
    if ind.get('ma60') is not None:
        pct = ind.get('price_vs_ma60')
        ma60_line = f"MA(60): {fp(ind['ma60'])} (현재가 대비 {pct:+.1f}%)\n" if pct is not None else f"MA(60): {fp(ind['ma60'])}\n"

    pct20 = ind.get('price_vs_ma20')
    ma20_line = f"MA(20): {fp(ind.get('ma20'))} (현재가 대비 {pct20:+.1f}%)\n" if pct20 is not None else f"MA(20): {fp(ind.get('ma20'))}\n"

    backtest_section = ''
    if backtest.get('win_rate') is not None:
        backtest_section = (
            f"\n[백테스트 결과 — 현재와 동일한 지표 조건]\n"
            f"과거 유사 신호 발생 횟수: {backtest['n_signals']}회\n"
            f"{backtest['forward_days']}거래일 후 +{backtest['min_return_pct']}% 이상 상승: {backtest['n_wins']}회\n"
            f"승률: {backtest['win_rate']}%\n"
            f"평균 수익률: {backtest['avg_return']:+.2f}%\n"
        )
    elif backtest.get('n_signals', 0) < 3:
        backtest_section = f"\n[백테스트] 과거 유사 신호가 {backtest.get('n_signals', 0)}회로 통계적으로 불충분합니다.\n"

    msg = (
        f"[{ticker_name} 기술적 분석 데이터]\n"
        f"현재가: {fp(cur)}\n"
        f"{ma20_line}"
        f"{ma60_line}"
        f"RSI(14): {ind.get('rsi', 'N/A')} (전일: {ind.get('rsi_prev', 'N/A')})\n"
        f"MACD 히스토그램: {ind.get('macd_hist', 'N/A')} (전일: {ind.get('macd_hist_prev', 'N/A')})\n"
        f"볼린저밴드 %B: {ind.get('bb_pct', 'N/A')} (상단: {fp(ind.get('bb_upper'))}, 하단: {fp(ind.get('bb_lower'))})\n"
        f"최근 20일 고점: {fp(ind.get('recent_high_20d'))}\n"
        f"최근 20일 저점: {fp(ind.get('recent_low_20d'))}\n"
        f"거래량 (20일 평균 대비): {ind.get('vol_ratio', 1):.1f}배"
        f"{backtest_section}\n\n"
        f"최근 뉴스:\n{news_lines}\n\n"
        f"위 데이터를 바탕으로 단기(수일~2주) 매매 조언을 제시해 주세요. "
        f"백테스트 승률이 있다면 반드시 근거로 언급하세요."
    )

    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=TRADING_SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': msg}],
    )

    raw = response.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {'signal': '분석 오류', 'signal_strength': '약', 'summary': raw, 'reasons': [], 'risks': []}
