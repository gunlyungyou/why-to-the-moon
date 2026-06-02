#!/usr/bin/env python3
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from dotenv import load_dotenv
from zoneinfo import ZoneInfo
from datetime import datetime, time as dtime
import json
import asyncio

load_dotenv(Path(__file__).parent / '.env')

from modules.stock import get_ticker_code, get_price_info, get_chart_data, is_overseas_index_ticker, get_market_context, get_surging_popular_stocks, refresh_market_data
from modules.news import get_naver_news, get_news_by_search
from modules.analyzer import explain_price_movement

KST = ZoneInfo('Asia/Seoul')
REFRESH_INTERVAL = 600  # 장중 10분마다 갱신


def _is_market_hours() -> bool:
    now = datetime.now(KST)
    return now.weekday() < 5 and dtime(9, 0) <= now.time() <= dtime(15, 30)


async def _cache_refresh_loop():
    while True:
        if _is_market_hours():
            await asyncio.to_thread(refresh_market_data)
            await asyncio.sleep(REFRESH_INTERVAL)
        else:
            await asyncio.sleep(60)  # 장 외엔 1분마다 시간만 체크


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_cache_refresh_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/popular")
async def popular():
    data = await asyncio.to_thread(get_surging_popular_stocks, 10)
    return data


@app.get("/api/analyze")
async def analyze(ticker_name: str):
    async def generate():
        try:
            yield f"data: {json.dumps({'step': 'stock'}, ensure_ascii=False)}\n\n"
            ticker = await asyncio.to_thread(get_ticker_code, ticker_name)
            is_index = is_overseas_index_ticker(ticker)
            price, chart, mkt_ctx = await asyncio.gather(
                asyncio.to_thread(get_price_info, ticker),
                asyncio.to_thread(get_chart_data, ticker, is_index),
                asyncio.to_thread(get_market_context, ticker, 'KRW' if not is_index else 'USD'),
            )
            yield f"data: {json.dumps({'step': 'stock_done', 'ticker': ticker, 'price': price, 'chart': chart}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'step': 'news'}, ensure_ascii=False)}\n\n"
            if price.get('is_index'):
                news = await asyncio.to_thread(get_news_by_search, price.get('ticker_name', ticker_name), 10)
            else:
                news = await asyncio.to_thread(get_naver_news, ticker, ticker_name, 10)
            yield f"data: {json.dumps({'step': 'news_done', 'news': news}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'step': 'analyzing'}, ensure_ascii=False)}\n\n"
            result = await asyncio.to_thread(explain_price_movement, ticker_name, price, news, chart, None, mkt_ctx)
            yield f"data: {json.dumps({'step': 'done', 'result': result}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'step': 'error', 'msg': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
