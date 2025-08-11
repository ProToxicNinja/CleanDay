# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json

from app.routes import game
from app.routes import market
from app.utils import genome_fingerprint, canonical_genome

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")

# expose a Jinja filter for genome fingerprint in templates
def _genome_fp_filter(value):
    try:
        if isinstance(value, str):
            g = json.loads(value)
        else:
            g = value
        return genome_fingerprint(g)
    except Exception:
        return "??????"

templates.env.filters['genome_fp'] = _genome_fp_filter
templates.env.filters['loads'] = json.loads

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# mount routers
app.include_router(game.router)
market.ensure_market_schema()
app.include_router(market.router)

# convenience root -> greenhouse
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/greenhouse", status_code=307)
