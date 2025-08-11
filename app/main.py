# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json

from app.routes import game
from app.routes import market
from app.utils import (
    genome_fingerprint,
    canonical_genome,
    uid,
    grant_starter_pack,
)
from app.db import get_conn, exec1, q, init_db

app = FastAPI()
init_db()
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


@app.middleware("http")
async def attach_player(request: Request, call_next):
    """Ensure each request has a persistent player id via cookie."""
    player_id = request.cookies.get("player_id")
    conn = get_conn()
    if not player_id:
        player_id = uid("player")
        exec1(conn, "INSERT INTO users(id) VALUES(?)", (player_id,))
        grant_starter_pack(conn, player_id)
    else:
        rows = q(conn, "SELECT id FROM users WHERE id=?", (player_id,))
        if not rows:
            exec1(conn, "INSERT INTO users(id) VALUES(?)", (player_id,))
            grant_starter_pack(conn, player_id)
    conn.close()
    request.state.player_id = player_id
    response = await call_next(request)
    if request.cookies.get("player_id") != player_id:
        response.set_cookie("player_id", player_id, max_age=60 * 60 * 24 * 365)
    return response

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

# convenience root -> greenhouse
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/greenhouse", status_code=307)
