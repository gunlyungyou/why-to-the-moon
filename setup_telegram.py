#!/usr/bin/env python3
"""
텔레그램 봇 설정 도우미

실행: python setup_telegram.py
"""
import requests
import os
from pathlib import Path
from dotenv import load_dotenv, set_key

ENV_PATH = Path(__file__).parent / '.env'
load_dotenv(ENV_PATH)


def step1_guide():
    print("""
=== 1단계: 텔레그램 봇 만들기 ===

1. 텔레그램 앱에서 @BotFather 검색 후 대화 시작
2. /newbot 입력
3. 봇 이름 입력 (예: MyStockAlertBot)
4. 봇 username 입력 (예: my_stock_alert_bot)  ← 반드시 _bot 으로 끝나야 함
5. BotFather가 토큰을 발급해줌

예시 토큰: 1234567890:ABCDEFghijklmnopqrstuvwxyz1234567890
""")


def step2_get_token():
    existing = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if existing:
        print(f"현재 저장된 토큰: {existing[:20]}...")
        use_existing = input("기존 토큰 사용? (y/n): ").strip().lower()
        if use_existing == 'y':
            return existing

    token = input("BotFather에서 받은 토큰을 입력하세요: ").strip()
    if not token:
        print("토큰이 없습니다. 취소합니다.")
        return None

    set_key(ENV_PATH, 'TELEGRAM_BOT_TOKEN', token)
    print("✅ 토큰 저장 완료")
    return token


def step3_get_chat_id(token: str):
    print("""
=== 3단계: Chat ID 확인 ===

1. 텔레그램에서 방금 만든 봇을 검색
2. 봇에게 아무 메시지나 보내기 (예: "안녕")
3. 아래에서 자동으로 Chat ID를 가져옵니다...
""")
    input("메시지를 보냈으면 Enter를 눌러주세요...")

    resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
    data = resp.json()

    if not data.get('ok') or not data.get('result'):
        print("❌ 메시지를 찾을 수 없습니다. 봇에게 메시지를 먼저 보내주세요.")
        return None

    chat_id = str(data['result'][-1]['message']['chat']['id'])
    name    = data['result'][-1]['message']['chat'].get('first_name', '')
    print(f"✅ Chat ID 확인: {chat_id}  (이름: {name})")

    set_key(ENV_PATH, 'TELEGRAM_CHAT_ID', chat_id)
    print("✅ Chat ID 저장 완료")
    return chat_id


def step4_test(token: str, chat_id: str):
    print("\n=== 4단계: 테스트 메시지 발송 ===")
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            'chat_id': chat_id,
            'text': '✅ StockAI 시장 경보 봇 연결 성공!\n\n매일 오전 8:50에 시장 경보를 보내드립니다.',
            'parse_mode': 'HTML',
        },
        timeout=10,
    )
    if resp.status_code == 200:
        print("✅ 테스트 메시지 발송 성공! 텔레그램을 확인하세요.")
    else:
        print(f"❌ 발송 실패: {resp.text}")


if __name__ == '__main__':
    print("=" * 50)
    print("  StockAI 텔레그램 경보 봇 설정")
    print("=" * 50)

    step1_guide()
    input("BotFather에서 봇을 만들었으면 Enter를 눌러주세요...")

    token = step2_get_token()
    if not token:
        exit(1)

    chat_id = step3_get_chat_id(token)
    if not chat_id:
        exit(1)

    step4_test(token, chat_id)

    print("""
=== 설정 완료! ===

이제 아래 명령어로 봇을 시작하세요:
  python alert_bot.py

봇이 실행되면:
  - 즉시 시장 현황을 한 번 발송
  - 이후 평일 08:50 / 토요일 09:00 자동 발송
""")
