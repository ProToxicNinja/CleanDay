from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from itsdangerous import Signer, BadSignature

from app.db import init_db
from app.routes.game import router as game_router
from app.utils import get_or_create_player

app = FastAPI(title="Plant Breeder Sim - Day 1")

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Signed cookie for player_id
SECRET = "change-me-in-production"
app.add_middleware(SessionMiddleware, secret_key=SECRET)

@app.on_event("startup")
def on_startup():
    init_db()

@app.middleware("http")
async def ensure_player(request: Request, call_next):
    signer = Signer(SECRET)
    signed_pid = request.cookies.get("player_id")

    if not signed_pid:
        new_id = get_or_create_player()
        request.state.player_id = new_id
        response: Response = await call_next(request)
        response.set_cookie("player_id", signer.sign(new_id.encode()).decode(), httponly=True, samesite="lax")
        return response
    else:
        try:
            pid = signer.unsign(signed_pid.encode()).decode()
            request.state.player_id = pid
        except BadSignature:
            new_id = get_or_create_player()
            request.state.player_id = new_id
            response: Response = await call_next(request)
            response.set_cookie("player_id", signer.sign(new_id.encode()).decode(), httponly=True, samesite="lax")
            return response

    return await call_next(request)

@app.get("/", response_class=HTMLResponse)
async def index(_: Request):
    return RedirectResponse(url="/greenhouse")

app.include_router(game_router)
