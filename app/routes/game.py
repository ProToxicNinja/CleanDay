import json
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.db import get_conn, q, exec1
from app.utils import uid, express_phenotype
from app.genetics.engine import simple_tick

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

@router.get("/greenhouse", response_class=HTMLResponse)
async def greenhouse(request: Request):
    player_id = request.state.player_id
    conn = get_conn()
    plants = q(conn, "SELECT * FROM plants WHERE user_id=? ORDER BY created_at DESC", (player_id,))
    seeds = q(conn, "SELECT * FROM seeds WHERE user_id=? ORDER BY species", (player_id,))

    plant_cards = []
    for row in plants:
        genome = json.loads(row["genome_json"])
        pheno = express_phenotype(genome)
        plant_cards.append({
            "id": row["id"],
            "species": row["species"],
            "age_days": row["age_days"],
            "health": round(row["health"], 3),
            "appearance": pheno["appearance"],
            "height_score": pheno["height_score"]
        })
    conn.close()
    return templates.TemplateResponse("greenhouse.html", {
        "request": request,
        "plants": plant_cards,
        "seeds": seeds
    })

@router.post("/plant_seed")
async def plant_seed(request: Request, seed_id: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()
    rows = q(conn, "SELECT * FROM seeds WHERE id=? AND user_id=?", (seed_id, player_id))
    if not rows:
        conn.close()
        return RedirectResponse(url="/greenhouse", status_code=303)
    lot = rows[0]
    if lot["qty"] <= 0:
        conn.close()
        return RedirectResponse(url="/greenhouse", status_code=303)

    exec1(conn, "UPDATE seeds SET qty=? WHERE id=?", (lot["qty"] - 1, seed_id))

    pid = uid("plant")
    exec1(conn,
          "INSERT INTO plants(id,user_id,species,genome_json,age_days,health) VALUES(?,?,?,?,?,?)",
          (pid, player_id, lot["species"], lot["genome_json"], 0, 1.0))
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

@router.post("/tick")
async def tick(request: Request):
    player_id = request.state.player_id
    conn = get_conn()
    plants = q(conn, "SELECT id, age_days, health FROM plants WHERE user_id=?", (player_id,))
    for p in plants:
        new_age, new_health = simple_tick(p["age_days"], p["health"])
        exec1(conn,
              "UPDATE plants SET age_days=?, health=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
              (new_age, new_health, p["id"]))
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

@router.post("/new_game")
async def new_game(request: Request):
    from app.utils import get_or_create_player
    player_id = request.state.player_id
    conn = get_conn()
    exec1(conn, "DELETE FROM plants WHERE user_id=?", (player_id,))
    exec1(conn, "DELETE FROM seeds WHERE user_id=?", (player_id,))
    _ = get_or_create_player()
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)
