#!/usr/bin/env python3
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from dotenv import load_dotenv
import json
import asyncio

load_dotenv(Path(__file__).parent / '.env')

from modules.stock import get_ticker_code, get_price_info, get_chart_data, is_overseas_index_ticker
from modules.news import get_naver_news, get_news_by_search
from modules.analyzer import explain_price_movement

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/analyze")
async def analyze(ticker_name: str):
    async def generate():
        try:
            yield f"data: {json.dumps({'step': 'stock'}, ensure_ascii=False)}\n\n"
            ticker = await asyncio.to_thread(get_ticker_code, ticker_name)
            is_index = is_overseas_index_ticker(ticker)
            price, chart = await asyncio.gather(
                asyncio.to_thread(get_price_info, ticker),
                asyncio.to_thread(get_chart_data, ticker, is_index),
            )
            yield f"data: {json.dumps({'step': 'stock_done', 'ticker': ticker, 'price': price, 'chart': chart}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'step': 'news'}, ensure_ascii=False)}\n\n"
            if price.get('is_index'):
                news = await asyncio.to_thread(get_news_by_search, price.get('ticker_name', ticker_name), 10)
            else:
                news = await asyncio.to_thread(get_naver_news, ticker, ticker_name, 10)
            yield f"data: {json.dumps({'step': 'news_done', 'news': news}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'step': 'analyzing'}, ensure_ascii=False)}\n\n"
            result = await asyncio.to_thread(explain_price_movement, ticker_name, price, news)
            yield f"data: {json.dumps({'step': 'done', 'result': result}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'step': 'error', 'msg': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
