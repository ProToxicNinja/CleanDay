import json
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.db import get_conn, q, exec1
from app.utils import uid, express_phenotype, next_generation_label, grant_starter_pack
from app.genetics.engine import simple_tick, recombine_genomes

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
            "generation": row["generation"],
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
          "INSERT INTO plants(id,user_id,species,genome_json,age_days,health,generation) VALUES(?,?,?,?,?,?,?)",
          (pid, player_id, lot["species"], lot["genome_json"], 0, 1.0, lot["generation"]))
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
    player_id = request.state.player_id
    conn = get_conn()
    exec1(conn, "DELETE FROM plants WHERE user_id=?", (player_id,))
    exec1(conn, "DELETE FROM seeds WHERE user_id=?", (player_id,))
    grant_starter_pack(conn, player_id)
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

# ---------- Breeding (selfing allowed) ----------

@router.get("/breeding", response_class=HTMLResponse)
async def breeding_room(request: Request):
    player_id = request.state.player_id
    conn = get_conn()
    plants = q(conn, "SELECT * FROM plants WHERE user_id=? ORDER BY created_at DESC", (player_id,))
    cards = []
    for row in plants:
        genome = json.loads(row["genome_json"])
        pheno = express_phenotype(genome)
        cards.append({
            "id": row["id"],
            "species": row["species"],
            "generation": row["generation"],
            "age_days": row["age_days"],
            "appearance": pheno["appearance"],
            "height_score": pheno["height_score"]
        })
    lots = q(conn, "SELECT * FROM seeds WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (player_id,))
    conn.close()
    return templates.TemplateResponse("breeding.html", {
        "request": request,
        "plants": cards,
        "lots": lots
    })

@router.post("/pollinate")
async def pollinate(request: Request,
                    mom_id: str = Form(...),
                    dad_id: str = Form(...),
                    lot_size: int = Form(8)):
    player_id = request.state.player_id
    conn = get_conn()
    moms = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (mom_id, player_id))
    dads = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (dad_id, player_id))
    if not moms or not dads:
        conn.close()
        return RedirectResponse(url="/breeding", status_code=303)

    mom = moms[0]; dad = dads[0]
    if mom["species"] != dad["species"]:
        conn.close()
        return RedirectResponse(url="/breeding", status_code=303)

    mom_g = json.loads(mom["genome_json"])
    dad_g = json.loads(dad["genome_json"])
    child_g = recombine_genomes(mom_g, dad_g)

    try:
        g_m = int(str(mom["generation"])[1:]) if mom["generation"] else 1
        g_d = int(str(dad["generation"])[1:]) if dad["generation"] else 1
        base = f"F{max(g_m, g_d)}"
    except:
        base = "F1"
    child_gen = next_generation_label(base)

    lot_id = uid("seed")
    parents = {"mom": mom["id"], "dad": dad["id"]}
    exec1(conn,
          "INSERT INTO seeds(id,user_id,species,genome_json,qty,generation,parents_json) VALUES(?,?,?,?,?,?,?)",
          (lot_id, player_id, mom["species"], json.dumps(child_g), max(2, min(24, lot_size)), child_gen, json.dumps(parents)))
    conn.close()
    return RedirectResponse(url="/breeding", status_code=303)