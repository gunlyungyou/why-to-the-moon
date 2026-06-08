#!/usr/bin/env python3
"""
시장 경보 텔레그램 봇
실행: python alert_bot.py

스케줄:
  평일 08:50  장 시작 전 경보
  토요일 09:00  미국 금요일 장 마감 결과 확인 (월요일 대비)
"""
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / '.env')

from apscheduler.schedulers.blocking import BlockingScheduler
from modules.market_alert import run_alert

scheduler = BlockingScheduler(timezone='Asia/Seoul')

scheduler.add_job(run_alert, 'cron', day_of_week='mon-fri', hour=8,  minute=50, id='weekday')
scheduler.add_job(run_alert, 'cron', day_of_week='sat',     hour=9,  minute=0,  id='saturday')

if __name__ == '__main__':
    print("=== 시장 경보 봇 시작 ===")
    print("스케줄: 평일 08:50 · 토요일 09:00")
    print("지금 즉시 1회 실행합니다...\n")
    run_alert()
    print("\n스케줄러 대기 중... (Ctrl+C 로 종료)")
    scheduler.start()
