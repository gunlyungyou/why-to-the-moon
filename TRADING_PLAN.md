# 자동매매 구현 계획

> 현재 StockAI 앱의 매매 신호를 활용한 단계별 자동매매 시스템 구축

---

## 전체 로드맵

```
1단계  아웃샘플 백테스트     (1~3일)   신호 신뢰도 검증
2단계  KIS API 연동          (1~2일)   모의투자 주문 테스트
3단계  자동매매 파이프라인   (3~5일)   신호 → 주문 자동화
4단계  리스크 관리           (2~3일)   손절/익절/한도 자동화
```

---

## 1단계: 아웃샘플 백테스트

### 현재 문제

`signal.py`의 `_backtest()`는 **인샘플(in-sample)** 검증입니다.  
신호를 정의한 데이터로 검증하기 때문에 과적합 가능성이 있습니다.

```
현재: [────────── 전체 2년 데이터 (신호 정의 + 검증) ──────────]
개선: [────── 앞 18개월 (신호 정의) ──────][── 뒤 6개월 (검증) ──]
```

### 구현 내용

**파일**: `modules/signal.py` → `_backtest()` 함수 수정

```python
def _backtest(df, indicators, forward_days=5, min_return=0.02):
    n = len(df)
    
    # 아웃샘플 분리: 마지막 25%는 검증용 (약 6개월)
    split = int(n * 0.75)
    train_df = df.iloc[:split]   # 신호 조건 정의용 (사용 안 함, 향후 ML 확장 대비)
    test_df  = df.iloc[split:]   # 실제 검증 구간
    
    # 검증 구간에서만 승률 계산
    returns = []
    for i in range(30, len(test_df) - forward_days - 1):
        # ... 기존 로직 동일 ...
    
    return {
        'n_signals': len(returns),
        'win_rate': ...,
        'avg_return': ...,
        'test_period': f"{test_df.index[0].date()} ~ {test_df.index[-1].date()}",
        'is_out_of_sample': True,   # UI에 표시
    }
```

**수수료 포함 (매우 중요)**

```python
# 수수료: 매수 0.015% + 매도 0.015% + 증권거래세 0.18% = 총 약 0.21%
TRANSACTION_COST = 0.0021

net_return = raw_return - TRANSACTION_COST
returns.append(net_return)
```

### 검증 기준 (진입 필터)

아웃샘플 결과 기준으로 신호를 걸러냅니다:

| 조건 | 기준값 | 의미 |
|------|--------|------|
| `win_rate` | > 60% | 랜덤(50%) 대비 유의미한 우위 |
| `avg_return` (수수료 후) | > 0.5% | 실제 수익 기대 |
| `n_signals` | > 10회 | 통계적으로 충분한 샘플 |

---

## 2단계: KIS API 연동

### API key 발급

1. [KIS Developers](https://apiportal.koreainvestment.com) 접속
2. 로그인 → 앱 등록 → `APP KEY` / `APP SECRET` 발급
3. **모의투자 전용 key 별도 발급** (실계좌와 다름)

### 환경 변수 추가 (`.env`)

```env
# 기존
ANTHROPIC_API_KEY=...

# 추가
KIS_APP_KEY=PSxxxxxxxxxxxxxxxxxx
KIS_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
KIS_ACCOUNT_NO=50xxxxxx-01        # 계좌번호
KIS_IS_MOCK=true                   # true=모의, false=실계좌
```

### 설치

```bash
pip install mojito2
```

`requirements.txt`에 추가:
```
mojito2>=0.1.40
```

### 기본 연동 테스트 (`kis_test.py`)

```python
import mojito
import os
from dotenv import load_dotenv

load_dotenv()

broker = mojito.KoreaInvestment(
    api_key=os.environ['KIS_APP_KEY'],
    api_secret=os.environ['KIS_APP_SECRET'],
    acc_no=os.environ['KIS_ACCOUNT_NO'],
    mock=os.environ.get('KIS_IS_MOCK', 'true') == 'true',
)

# 잔고 조회
balance = broker.fetch_balance()
print("보유 잔고:", balance)

# 삼성전자 현재가 조회
price = broker.fetch_price('005930')
print("삼성전자 현재가:", price)

# 모의투자 매수 주문 (1주, 시장가)
order = broker.create_market_buy_order(
    symbol='005930',
    quantity=1,
)
print("주문 결과:", order)
```

### 주요 API 함수

| 함수 | 용도 |
|------|------|
| `broker.fetch_balance()` | 잔고/보유종목 조회 |
| `broker.fetch_price(symbol)` | 현재가 조회 |
| `broker.create_market_buy_order(symbol, qty)` | 시장가 매수 |
| `broker.create_limit_buy_order(symbol, qty, price)` | 지정가 매수 |
| `broker.create_market_sell_order(symbol, qty)` | 시장가 매도 |
| `broker.create_limit_sell_order(symbol, qty, price)` | 지정가 매도 |
| `broker.cancel_order(order_no)` | 주문 취소 |

---

## 3단계: 자동매매 파이프라인

### 아키텍처

```
매일 오전 8:50 (장 시작 10분 전)
  └── 신호 생성 (watchlist 10종목)
        └── 필터: win_rate > 60% AND avg_return > 0.5% AND signal == "매수 고려"
              └── 포지션 사이징 계산
                    └── 매수 주문 실행 (9:00 장 시작 후)
                          └── DB에 포지션 기록

매일 오후 3:00 (장 마감 직전)
  └── 보유 포지션 점검
        ├── 목표가 도달 → 익절 주문
        ├── 손절가 도달 → 손절 주문
        └── 보유 N일 초과 → 청산 주문
```

### 신규 파일 구조

```
auto_trading/
  ├── trader.py          # 메인 실행 파일
  ├── portfolio.py       # 포지션 관리
  ├── risk.py            # 리스크 관리 규칙
  └── scheduler.py       # 스케줄러
```

### `auto_trading/portfolio.py`

```python
import sqlite3
from datetime import datetime

DB_PATH = 'trading.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            name TEXT,
            entry_price REAL,
            quantity INTEGER,
            entry_date TEXT,
            target_price REAL,
            stop_loss REAL,
            status TEXT DEFAULT 'open',   -- open / closed
            exit_price REAL,
            exit_date TEXT,
            pnl REAL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            symbol TEXT,
            action TEXT,    -- buy / sell
            price REAL,
            quantity INTEGER,
            reason TEXT
        )
    ''')
    conn.commit()
    conn.close()

def open_position(symbol, name, entry_price, quantity, target_price, stop_loss):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        INSERT INTO positions (symbol, name, entry_price, quantity, entry_date, target_price, stop_loss)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (symbol, name, entry_price, quantity, datetime.now().isoformat(), target_price, stop_loss))
    conn.commit()
    conn.close()

def get_open_positions():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT * FROM positions WHERE status='open'").fetchall()
    conn.close()
    return rows

def close_position(position_id, exit_price, reason):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        UPDATE positions
        SET status='closed', exit_price=?, exit_date=?, pnl=?
        WHERE id=?
    ''', (exit_price, datetime.now().isoformat(),
          exit_price - conn.execute("SELECT entry_price FROM positions WHERE id=?", (position_id,)).fetchone()[0],
          position_id))
    conn.commit()
    conn.close()
```

### `auto_trading/trader.py`

```python
import os
import mojito
from dotenv import load_dotenv
from modules.signal import get_chart_and_analysis
from modules.analyzer import advise_trading
from modules.stock import get_ticker_code, get_price_info
from modules.news import get_naver_news
from auto_trading.portfolio import open_position, get_open_positions, close_position
from auto_trading.risk import can_open_position, calc_quantity

load_dotenv()

WATCHLIST = [
    ('삼성전자', '005930'),
    ('SK하이닉스', '000660'),
    ('현대차', '005380'),
    ('기아', '000270'),
    ('NAVER', '035420'),
    ('카카오', '035720'),
    ('POSCO홀딩스', '005490'),
    ('셀트리온', '068270'),
    ('삼성바이오로직스', '207940'),
    ('LG에너지솔루션', '373220'),
]

broker = mojito.KoreaInvestment(
    api_key=os.environ['KIS_APP_KEY'],
    api_secret=os.environ['KIS_APP_SECRET'],
    acc_no=os.environ['KIS_ACCOUNT_NO'],
    mock=os.environ.get('KIS_IS_MOCK', 'true') == 'true',
)


def run_morning_scan():
    """오전 신호 스캔 + 매수 주문"""
    print("=== 오전 신호 스캔 시작 ===")
    balance = broker.fetch_balance()
    total_asset = float(balance['output2'][0]['tot_evlu_amt'])  # 총 평가금액

    for name, code in WATCHLIST:
        try:
            chart_data = get_chart_and_analysis(code)
            bt = chart_data['backtest']
            ind = chart_data['indicators']

            # 진입 필터
            if bt.get('win_rate') is None or bt['win_rate'] < 60:
                print(f"[SKIP] {name}: 승률 부족 ({bt.get('win_rate')}%)")
                continue
            if bt.get('avg_return', 0) < 0.5:
                print(f"[SKIP] {name}: 평균 수익 부족 ({bt.get('avg_return')}%)")
                continue

            price_info = get_price_info(code)
            news = get_naver_news(code, name, 5)
            result = advise_trading(name, price_info, ind, bt, news)

            if result.get('signal') != '매수 고려':
                print(f"[SKIP] {name}: 매수 신호 아님 ({result.get('signal')})")
                continue

            # 리스크 관리 통과 여부
            if not can_open_position(total_asset):
                print(f"[STOP] 리스크 한도 초과, 신규 진입 중단")
                break

            current_price = price_info['current_price']
            quantity = calc_quantity(total_asset, current_price, risk_pct=0.02)
            if quantity < 1:
                continue

            # 매수 주문
            order = broker.create_market_buy_order(symbol=code, quantity=quantity)
            print(f"[BUY] {name} {quantity}주 @ {current_price:,}원")

            # 포지션 기록
            target = result.get('target_price')  # Claude가 제시한 목표가 파싱 필요
            stop = result.get('stop_loss')        # Claude가 제시한 손절가 파싱 필요
            open_position(code, name, current_price, quantity, target, stop)

        except Exception as e:
            print(f"[ERROR] {name}: {e}")


def run_afternoon_check():
    """오후 보유 포지션 점검 + 익절/손절"""
    print("=== 오후 포지션 점검 ===")
    positions = get_open_positions()

    for pos in positions:
        pos_id, symbol, name, entry_price, qty, entry_date, target, stop, *_ = pos
        price_info = get_price_info(symbol)
        current = price_info['current_price']
        pnl_pct = (current - entry_price) / entry_price * 100

        if target and current >= target:
            broker.create_market_sell_order(symbol=symbol, quantity=qty)
            close_position(pos_id, current, 'target_hit')
            print(f"[SELL/익절] {name} {pnl_pct:+.2f}%")

        elif stop and current <= stop:
            broker.create_market_sell_order(symbol=symbol, quantity=qty)
            close_position(pos_id, current, 'stop_loss')
            print(f"[SELL/손절] {name} {pnl_pct:+.2f}%")

        else:
            print(f"[HOLD] {name} {pnl_pct:+.2f}%")
```

### `auto_trading/scheduler.py`

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from auto_trading.trader import run_morning_scan, run_afternoon_check

scheduler = BlockingScheduler(timezone='Asia/Seoul')

# 평일 오전 9:05 (장 시작 후 5분)
scheduler.add_job(run_morning_scan, 'cron',
                  day_of_week='mon-fri', hour=9, minute=5)

# 평일 오후 3:15 (장 마감 후 15분)
scheduler.add_job(run_afternoon_check, 'cron',
                  day_of_week='mon-fri', hour=15, minute=15)

if __name__ == '__main__':
    print("자동매매 스케줄러 시작")
    scheduler.start()
```

설치:
```bash
pip install apscheduler
```

---

## 4단계: 리스크 관리

### `auto_trading/risk.py`

```python
from auto_trading.portfolio import get_open_positions

# 리스크 파라미터
MAX_POSITIONS     = 5        # 최대 동시 보유 종목 수
MAX_POSITION_PCT  = 0.02     # 종목당 최대 비중 (총 자산의 2%)
MAX_DAILY_LOSS    = 0.02     # 일일 최대 손실 한도 (2%)
STOP_LOSS_PCT     = 0.03     # 손절 기준 (-3%)
TAKE_PROFIT_PCT   = 0.06     # 익절 기준 (+6%), Claude 목표가 없을 때 기본값


def can_open_position(total_asset: float) -> bool:
    """신규 진입 가능 여부 판단"""
    positions = get_open_positions()

    # 1) 최대 보유 종목 수 초과
    if len(positions) >= MAX_POSITIONS:
        return False

    # 2) 일일 실현 손실 한도 초과
    daily_pnl = sum(p['pnl'] for p in positions if p['exit_date'][:10] == today())
    if daily_pnl < -(total_asset * MAX_DAILY_LOSS):
        return False

    return True


def calc_quantity(total_asset: float, price: float, risk_pct: float = MAX_POSITION_PCT) -> int:
    """포지션 사이징: 총 자산의 risk_pct 비중"""
    budget = total_asset * risk_pct
    return int(budget // price)


def calc_stop_loss(entry_price: float) -> float:
    return round(entry_price * (1 - STOP_LOSS_PCT))


def calc_take_profit(entry_price: float) -> float:
    return round(entry_price * (1 + TAKE_PROFIT_PCT))


def today():
    from datetime import date
    return date.today().isoformat()
```

### 리스크 규칙 요약

| 규칙 | 값 | 이유 |
|------|-----|------|
| 종목당 최대 비중 | 2% | 1종목 -50% 나도 전체 -1% |
| 최대 동시 보유 | 5종목 | 최대 손실 노출 10% |
| 손절 기준 | -3% | 기댓값 유지 |
| 익절 기준 | +6% (기본) | 손익비 2:1 |
| 일일 손실 한도 | -2% | 연속 손실 시 자동 중단 |

---

## 단계별 체크리스트

### 1단계 완료 기준
- [ ] 아웃샘플 승률이 60% 이상인 종목 존재 확인
- [ ] 수수료 포함 평균 수익률 > 0.5% 확인
- [ ] UI에 "아웃샘플 기준" 표시 추가

### 2단계 완료 기준
- [ ] KIS 모의투자 API key 발급
- [ ] `.env`에 KIS 설정 추가
- [ ] `kis_test.py` 실행 → 잔고 조회 성공
- [ ] 모의투자 매수/매도 주문 1회 성공

### 3단계 완료 기준
- [ ] `auto_trading/` 폴더 구조 생성
- [ ] `trading.db` 포지션 DB 초기화
- [ ] 스케줄러 실행 → 신호 스캔 로그 확인
- [ ] 모의투자 자동 매수 1회 성공

### 4단계 완료 기준
- [ ] 손절/익절 자동 실행 확인
- [ ] 일일 손실 한도 초과 시 신규 진입 중단 확인
- [ ] 1개월 모의투자 성과 기록

---

## 주의사항

> **반드시 모의투자에서 최소 1개월 이상 검증 후 실계좌 전환**
>
> 자동매매 투자 손실에 대한 책임은 투자자 본인에게 있습니다.
> 이 코드는 교육/참고 목적이며 수익을 보장하지 않습니다.
