#!/usr/bin/env python3
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from dotenv import load_dotenv
import json
import asyncio
import threading

load_dotenv(Path(__file__).parent / '.env')

from modules.stock import get_ticker_code, get_price_info
from modules.news import get_naver_news
from modules.analyzer import stream_price_movement

app = FastAPI()
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/analyze")
async def analyze(ticker_name: str):
    async def generate():
        loop = asyncio.get_event_loop()
        try:
            yield f"data: {json.dumps({'step': 'stock'}, ensure_ascii=False)}\n\n"

            ticker = await asyncio.to_thread(get_ticker_code, ticker_name)
            price = await asyncio.to_thread(get_price_info, ticker)

            yield f"data: {json.dumps({'step': 'stock_done', 'ticker': ticker, 'price': price}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'step': 'news'}, ensure_ascii=False)}\n\n"

            news = await asyncio.to_thread(get_naver_news, ticker, ticker_name, 10)

            yield f"data: {json.dumps({'step': 'news_done', 'news': news}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'step': 'analyzing'}, ensure_ascii=False)}\n\n"

            q: asyncio.Queue = asyncio.Queue()

            def run_stream():
                try:
                    for token in stream_price_movement(ticker_name, price, news):
                        asyncio.run_coroutine_threadsafe(q.put(('text', token)), loop)
                    asyncio.run_coroutine_threadsafe(q.put(('done', None)), loop)
                except Exception as e:
                    asyncio.run_coroutine_threadsafe(q.put(('error', str(e))), loop)

            thread = threading.Thread(target=run_stream, daemon=True)
            thread.start()

            while True:
                kind, val = await q.get()
                if kind == 'text':
                    yield f"data: {json.dumps({'step': 'text', 'text': val}, ensure_ascii=False)}\n\n"
                elif kind == 'done':
                    break
                elif kind == 'error':
                    yield f"data: {json.dumps({'step': 'error', 'msg': val}, ensure_ascii=False)}\n\n"
                    return

            thread.join()
            yield f"data: {json.dumps({'step': 'done'}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'step': 'error', 'msg': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
