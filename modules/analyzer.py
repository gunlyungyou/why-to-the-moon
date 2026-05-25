import os
import anthropic

CLAUDE_MODEL = 'claude-sonnet-4-6'

SYSTEM_PROMPT = """You are a Korean stock market expert. Always respond in Korean (한국어로만 답변하세요).

주어진 주가 데이터와 뉴스를 바탕으로 주가 변동 원인을 일반인도 이해할 수 있게 설명하세요.

분석 시 다음 원칙을 따르세요:
- 반드시 한국어로 답변
- 주가 변동 시점과 뉴스 발생 시점의 연관성에 집중
- 업종 전반보다 해당 종목 특유의 요인 우선
- 3~5문장으로 간결하게
- 불확실한 내용은 "~로 보입니다", "~가 영향을 미친 것으로 추정됩니다" 등으로 표현
- 뉴스가 부족하면 시장 전반 흐름이나 섹터 이슈로 추론 가능 여부를 언급"""


def _build_user_message(ticker_name, price_info, news_items, disclosures=None):
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

    return (
        f"{ticker_name}이(가) 오늘 9:00 시가({open_str})부터 "
        f"{as_of} 현재({current_str})까지 {sign}{rate}% {direction}했습니다.\n\n"
        f"관련 뉴스:\n{news_lines}"
        f"{disclosure_lines}\n\n"
        f"이 주가 변동의 원인을 분석해 주세요."
    )


def explain_price_movement(ticker_name, price_info, news_items, disclosures=None):
    user_message = _build_user_message(ticker_name, price_info, news_items, disclosures)
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': user_message}],
    )
    return response.content[0].text


def stream_price_movement(ticker_name, price_info, news_items, disclosures=None):
    user_message = _build_user_message(ticker_name, price_info, news_items, disclosures)
    client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': user_message}],
    ) as stream:
        for text in stream.text_stream:
            yield text
