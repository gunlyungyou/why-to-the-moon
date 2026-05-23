# 주가 등락 원인 분석 앱 — 설계 플랜

## 개요

사용자가 종목명(예: 삼성전자)을 입력하면, **오늘 장 시작(9시)부터 현재 시각까지**의 주가 변동을 계산하고, 해당 시간대의 뉴스·공시를 수집해 Claude API로 등락 원인을 설명해 주는 웹 앱.

---

## 핵심 흐름

```
사용자 입력 (종목명/코드)
       ↓
[1] 주가 데이터 수집
    - 오늘 9:00 시가 → 현재가 등락률 계산
    - 분봉 차트 데이터 (급등/급락 시점 포착)
       ↓
[2] 뉴스·공시 수집
    - 장 시작 ~ 현재 시각 범위의 뉴스 크롤링
    - 주요 공시(DART) 확인
       ↓
[3] Claude API 분석
    - 가격 변동 + 뉴스 컨텍스트 → 원인 설명 생성
       ↓
[4] 결과 출력
    - 등락률, 분봉 차트, AI 설명 표시
```

---

## 기술 스택

| 레이어 | 선택 | 이유 |
|---|---|---|
| 언어 | Python 3.11+ | 금융 데이터 생태계 풍부 |
| 웹 프레임워크 | FastAPI | 비동기 처리, 빠른 개발 |
| 프론트엔드 | Jinja2 + vanilla JS | 의존성 최소화 |
| 주가 데이터 | `pykrx` (한국거래소 직접) | 실시간 국내 주식 지원 |
| 뉴스 수집 | 네이버 금융 뉴스 크롤링 + DART OpenAPI | 한국 주요 뉴스 커버 |
| AI 분석 | Anthropic Claude API (`claude-sonnet-4-6`) | 한국어 설명 품질 |
| 차트 | Chart.js (프론트) | 경량, CDN 사용 가능 |

---

## 디렉토리 구조

```
stock_explainer/
├── PLAN.md                  ← 이 파일
├── README.md
├── .env.example             ← API 키 템플릿
├── requirements.txt
├── main.py                  ← FastAPI 앱 진입점
├── modules/
│   ├── stock.py             ← 주가 데이터 수집 (pykrx)
│   ├── news.py              ← 뉴스·공시 크롤링
│   └── analyzer.py          ← Claude API 분석
├── templates/
│   └── index.html           ← 메인 UI
└── static/
    └── style.css
```

---

## 모듈 상세 설계

### 1. `modules/stock.py` — 주가 데이터

```python
# 핵심 함수
get_ticker_code(name: str) -> str        # "삼성전자" → "005930"
get_today_ohlcv(ticker: str) -> dict     # 오늘 분봉 OHLCV
get_price_change(ticker: str) -> dict    # 시가 대비 현재가 등락률
```

- `pykrx.stock.get_market_ohlcv_by_ticker()` 로 일봉
- `pykrx.stock.get_market_ohlcv_by_date()` 로 분봉 (장중)
- 시장 미개장 시 오류 처리 (9:00~15:30 외)

### 2. `modules/news.py` — 뉴스·공시 수집

```python
get_naver_news(ticker_name: str, from_time: datetime, to_time: datetime) -> list[dict]
get_dart_disclosures(ticker: str, today: date) -> list[dict]
```

- 네이버 금융 종목 뉴스 (`https://finance.naver.com/item/news.naver?code=XXXXXX`) 파싱
- DART OpenAPI (`https://opendart.fss.or.kr`) 오늘 공시 조회
- 수집 항목: 제목, 요약, 출처, 발행 시각

### 3. `modules/analyzer.py` — Claude API 분석

```python
explain_price_movement(
    ticker_name: str,
    price_change: dict,   # 등락률, 시가, 현재가, 분봉 추이
    news_items: list[dict],
    disclosures: list[dict]
) -> str
```

**프롬프트 구조:**
```
시스템: 당신은 한국 주식시장 전문가입니다. 주어진 데이터를 바탕으로
        주가 변동 원인을 일반인도 이해할 수 있게 설명하세요.

사용자: [종목명]이 오늘 9:00~[현재시각] 동안 [등락률]% [상승/하락]했습니다.
        - 분봉 추이: ...
        - 관련 뉴스: ...
        - 공시: ...
        원인을 분석해 주세요.
```

- `claude-sonnet-4-6` 사용
- 프롬프트 캐싱 (`cache_control`) 적용 (시스템 프롬프트)
- 응답은 3~5문장의 한국어 설명

### 4. `main.py` — FastAPI 라우터

```
GET  /              → index.html 렌더링
POST /analyze       → { ticker_name } 받아서 분석 결과 JSON 반환
GET  /health        → 서버 상태 확인
```

---

## UI 설계

```
┌─────────────────────────────────────────┐
│  주가 등락 원인 분석기                    │
│                                         │
│  종목명 입력: [삼성전자        ] [분석]  │
│                                         │
│  ─────────────────────────────────────  │
│  삼성전자 (005930)                       │
│  9:00 시가 70,000원 → 현재 77,000원     │
│  ▲ +10.0%  오전 10:23 기준             │
│                                         │
│  [분봉 차트 영역 - Chart.js]            │
│                                         │
│  ─────────────────────────────────────  │
│  📊 AI 분석 결과                        │
│  오늘 삼성전자는 장 시작 직후부터 강하게  │
│  상승했습니다. 주요 원인으로는 ...       │
│                                         │
│  📰 참고 뉴스 (3건)                     │
│  · [09:15] 삼성전자, 엔비디아에 HBM4 ...│
└─────────────────────────────────────────┘
```

---

## 구현 단계

### Phase 1 — 핵심 기능 (MVP)
- [ ] `pykrx`로 삼성전자 오늘 시가/현재가/등락률 수집
- [ ] 네이버 금융 뉴스 크롤링 (오늘 뉴스 10건)
- [ ] Claude API로 설명 생성 (CLI 버전)
- [ ] 기본 동작 검증

### Phase 2 — 웹 앱화
- [ ] FastAPI 서버 구축
- [ ] 종목 검색 UI (종목명 → 코드 자동 변환)
- [ ] 분봉 차트 표시 (Chart.js)
- [ ] DART 공시 연동

### Phase 3 — 품질 개선
- [ ] 종목 자동완성 (삼성, 카카오 등 입력 시 후보 표시)
- [ ] 장 시간 외 접속 시 전일 종가 기준 설명 모드
- [ ] 설명 캐싱 (같은 종목 1분 내 재요청 시 캐시 반환)
- [ ] 에러 처리 (상장폐지 종목, 데이터 없음 등)

---

## 필요한 API 키 / 환경 변수

```env
ANTHROPIC_API_KEY=sk-ant-...       # Claude API (필수)
DART_API_KEY=...                   # DART OpenAPI (선택, 공시 조회용)
```

> 네이버 금융 뉴스는 별도 API 키 없이 HTML 파싱으로 수집

---

## 제약 및 주의사항

- **pykrx 분봉 데이터**: 장중(9:00~15:30)에만 유효, 당일 데이터는 15분 지연될 수 있음
- **뉴스 크롤링**: 네이버 robots.txt 준수, 과도한 요청 금지 (요청 간 1~2초 간격)
- **Claude API 비용**: 요청당 약 $0.003~0.01 수준 (Sonnet 기준)
- **장 외 시간 접속**: "현재 장이 열려있지 않습니다" 안내 + 전일 마감 기준 모드 제공

---

## 다음 액션

1. `requirements.txt` 작성 및 가상환경 설정
2. Phase 1 MVP 구현 시작 (`modules/stock.py` → `modules/news.py` → `modules/analyzer.py` 순서)
3. CLI로 동작 확인 후 FastAPI 서버 래핑
