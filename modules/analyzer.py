import os
import json
import re
import anthropic

CLAUDE_MODEL = 'claude-sonnet-4-6'

SYSTEM_PROMPT = """당신은 한국 주식 시장 전문가입니다. 반드시 한국어로, 반드시 JSON 형식으로만 답변하세요.

주어진 주가 데이터와 뉴스를 분석하고, 아래 JSON만 출력하세요 (마크다운 코드블록 없이):

{
  "headline": "핵심 원인 한 줄 (15자 이내, 예: '노사 갈등 → 투자심리 악화')",
  "reasons": ["주요 원인 1 (20자 이내)", "주요 원인 2 (20자 이내)"],
  "detail": "상세 설명 2~3문장."
}

원칙:
- headline: 인과관계(→)로 핵심 원인 압축
- reasons: 2~3개, 각 20자 이내의 구체적 원인
- detail: 뉴스와 주가 변동의 연관성 중심, 불확실한 내용은 '~로 보입니다' 표현
- 뉴스가 부족하면 시장 흐름 기반 추론 가능하나 불확실성 명시"""


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
        f"{ticker_name}이(가) 오늘 시가({open_str})부터 "
        f"{as_of} 현재({current_str})까지 {sign}{rate}% {direction}했습니다.\n\n"
        f"관련 뉴스:\n{news_lines}"
        f"{disclosure_lines}\n\n"
        f"이 주가 변동의 원인을 분석해 주세요."
    )


def explain_price_movement(ticker_name, price_info, news_items, disclosures=None) -> dict:
    user_message = _build_user_message(ticker_name, price_info, news_items, disclosures)
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
        return {'headline': '분석 완료', 'reasons': [], 'detail': raw}
