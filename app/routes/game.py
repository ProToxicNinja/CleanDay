import json
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from app.db import get_conn, q, exec1
from app.utils import (
    uid, express_phenotype, next_generation_label, grant_starter_pack,
    compute_lot_qty, preview_cross_stats,
    ensure_slots, get_first_empty_slot, bind_plant_to_slot, unbind_plant_from_slot,
    get_env_for_plant
)
from app.genetics.engine import simple_tick, recombine_genomes, BASE_FRUIT_DAYS, fruit_days_with_env, compute_stage

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

# ---------- Sprites (SVG on the fly) ----------
@router.get("/sprite/{species}/{stage}.svg")
async def sprite(species: str, stage: str):
    species = species.lower()
    stage = stage.lower()
    # colors per species (placeholder palette)
    base = {"pea":"#6fc36f","tomato":"#e05b5b","marigold":"#f5a623"}.get(species, "#9aa0ae")
    # stage outline/intensity
    stroke = {"seedling":"#94d27d","juvenile":"#7db6e0","mature":"#ceb26d","flowering":"#e48bd1","spent":"#555a66"}.get(stage,"#9aa0ae")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60" viewBox="0 0 80 60">
  <rect x="6" y="46" width="68" height="10" rx="3" fill="#3a3f55"/>
  <path d="M40 46 C42 38 42 30 40 22" stroke="{stroke}" stroke-width="3" fill="none"/>
  <circle cx="40" cy="20" r="10" fill="{base}" opacity="{0.9 if stage in ('flowering','mature') else 0.6}"/>
  {"<circle cx='40' cy='12' r='5' fill='#ffd4f5'/>" if stage == "flowering" else ""}
  {"<line x1='30' y1='32' x2='20' y2='26' stroke='"+stroke+"' stroke-width='3'/>" if stage in ("juvenile","mature","flowering") else ""}
  {"<line x1='50' y1='32' x2='60' y2='26' stroke='"+stroke+"' stroke-width='3'/>" if stage in ("juvenile","mature","flowering") else ""}
  {"<line x1='38' y1='46' x2='42' y2='46' stroke='#273' stroke-width='4'/>"}
</svg>"""
    return Response(content=svg, media_type="image/svg+xml")

@router.get("/greenhouse", response_class=HTMLResponse)
async def greenhouse(request: Request):
    player_id = request.state.player_id
    conn = get_conn()
    ensure_slots(conn, player_id, 6)
    plants = q(conn, "SELECT * FROM plants WHERE user_id=? ORDER BY created_at DESC", (player_id,))
    seeds  = q(conn, "SELECT * FROM seeds  WHERE user_id=? ORDER BY species", (player_id,))
    fruits = q(conn, "SELECT * FROM fruits WHERE user_id=? ORDER BY created_at DESC", (player_id,))
    slots  = q(conn, "SELECT * FROM slots  WHERE user_id=? ORDER BY created_at ASC", (player_id,))

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
            "stage": row["stage"],
            "appearance": pheno["appearance"],
            "height_score": pheno["height_score"]
        })
    conn.close()
    return templates.TemplateResponse("greenhouse.html", {
        "request": request, "plants": plant_cards, "seeds": seeds,
        "fruits": fruits, "slots": slots
    })

@router.post("/slot_update")
async def slot_update(request: Request, slot_id: str = Form(...), soil: str = Form(...), light: str = Form(...),
                      water: str = Form(...), temp: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()
    exec1(conn, "UPDATE slots SET soil=?, light=?, water=?, temp=? WHERE id=? AND user_id=?",
          (soil, light, water, temp, slot_id, player_id))
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

@router.post("/plant_seed")
async def plant_seed(request: Request, seed_id: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()
    ensure_slots(conn, player_id, 6)
    rows = q(conn, "SELECT * FROM seeds WHERE id=? AND user_id=?", (seed_id, player_id))
    if not rows:
        conn.close(); return RedirectResponse(url="/greenhouse", status_code=303)
    lot = rows[0]
    if lot["qty"] <= 0:
        conn.close(); return RedirectResponse(url="/greenhouse", status_code=303)

    slot = get_first_empty_slot(conn, player_id)
    if not slot:
        conn.close(); return RedirectResponse(url="/greenhouse", status_code=303)

    exec1(conn, "UPDATE seeds SET qty=? WHERE id=?", (lot["qty"] - 1, seed_id))
    pid = uid("plant")
    exec1(conn, "INSERT INTO plants(id,user_id,species,genome_json,age_days,health,generation,stage) VALUES(?,?,?,?,?,?,?,?)",
          (pid, player_id, lot["species"], lot["genome_json"], 0, 1.0, lot["generation"], "seedling"))
    bind_plant_to_slot(conn, slot["id"], pid)
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

@router.post("/tick")
async def tick(request: Request):
    player_id = request.state.player_id
    conn = get_conn()
    # plants: env-aware tick
    plants = q(conn, "SELECT id, age_days, health FROM plants WHERE user_id=?", (player_id,))
    for p in plants:
        env = get_env_for_plant(conn, player_id, p["id"])
        new_age, new_health, new_stage = simple_tick(p["age_days"], p["health"], env)
        exec1(conn,
              "UPDATE plants SET age_days=?, health=?, stage=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
              (new_age, new_health, new_stage, p["id"]))
    # fruits: speed by env of mom plant's slot (approx)
    fruits = q(conn, "SELECT * FROM fruits WHERE user_id=? AND status='growing'", (player_id,))
    for f in fruits:
        env = get_env_for_plant(conn, player_id, f["mom_id"])
        # dynamic fruit time based on env
        days_req = fruit_days_with_env(env)
        remain = int(f["days_remaining"]) - 1
        status = "ripe" if remain <= 0 else "growing"
        exec1(conn, "UPDATE fruits SET days_remaining=?, status=? WHERE id=?",
              (max(0, remain), status, f["id"]))
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

@router.post("/new_game")
async def new_game(request: Request):
    player_id = request.state.player_id
    conn = get_conn()
    exec1(conn, "DELETE FROM plants WHERE user_id=?", (player_id,))
    exec1(conn, "DELETE FROM seeds  WHERE user_id=?", (player_id,))
    exec1(conn, "DELETE FROM fruits WHERE user_id=?", (player_id,))
    exec1(conn, "DELETE FROM slots  WHERE user_id=?", (player_id,))
    ensure_slots(conn, player_id, 6)
    grant_starter_pack(conn, player_id)
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

# ---------- Breeding flow: flowering only → FRUIT (delayed seeds) ----------

@router.get("/breeding", response_class=HTMLResponse)
async def breeding_room(request: Request):
    player_id = request.state.player_id
    conn = get_conn()
    plants = q(conn, "SELECT * FROM plants WHERE user_id=? ORDER BY created_at DESC", (player_id,))
    # cards
    cards = []
    for row in plants:
        genome = json.loads(row["genome_json"])
        pheno = express_phenotype(genome)
        cards.append({
            "id": row["id"],
            "species": row["species"],
            "generation": row["generation"],
            "age_days": row["age_days"],
            "stage": row["stage"],
            "appearance": pheno["appearance"],
            "height_score": pheno["height_score"]
        })
    fruits = q(conn, "SELECT * FROM fruits WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (player_id,))
    conn.close()
    err = request.query_params.get("err")
    return templates.TemplateResponse("breeding.html", {
        "request": request,
        "plants": cards,
        "fruits": fruits,
        "err": err
    })

@router.post("/preview_cross", response_class=HTMLResponse)
async def preview_cross(request: Request,
                        mom_id: str = Form(...),
                        dad_id: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()
    mom = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (mom_id, player_id))
    dad = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (dad_id, player_id))
    conn.close()
    if not mom or not dad:
        return HTMLResponse("<div class='muted'>Select two plants.</div>")
    mom, dad = mom[0], dad[0]
    mom_g = json.loads(mom["genome_json"])
    dad_g = json.loads(dad["genome_json"])
    stats = preview_cross_stats(mom_g, dad_g)
    # tiny fragment
    return HTMLResponse(f"""
<div class="card" style="margin-top:8px;">
  <strong>Preview</strong>
  <div class="muted">Requires both parents at <em>flowering</em>.</div>
  <ul>
    <li>Colored petals: <strong>{round(stats['p_colored']*100)}%</strong></li>
    <li>Variegation (vv): <strong>{round(stats['p_variegated']*100)}%</strong></li>
    <li>Expected height score: <strong>{stats['h_mean']:.1f}</strong> / 8</li>
    <li>Stability (fixed loci): <strong>{round(stats['stability']*100)}%</strong></li>
  </ul>
</div>
""")

@router.post("/pollinate")
async def pollinate(request: Request,
                    mom_id: str = Form(...),
                    dad_id: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()
    moms = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (mom_id, player_id))
    dads = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (dad_id, player_id))
    if not moms or not dads:
        conn.close()
        return RedirectResponse(url="/breeding?err=notfound", status_code=303)

    mom = moms[0]; dad = dads[0]
    if mom["species"] != dad["species"]:
        conn.close()
        return RedirectResponse(url="/breeding?err=species", status_code=303)
    if mom["stage"] != "flowering" or dad["stage"] != "flowering":
        conn.close()
        return RedirectResponse(url="/breeding?err=stage", status_code=303)

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

    qty = compute_lot_qty(float(mom["health"]), float(dad["health"]), mom["id"] == dad["id"])
    fruit_id = uid("fruit")
    # fruit time based on env of mom slot
    env = get_env_for_plant(conn, player_id, mom["id"])
    days = fruit_days_with_env(env)
    
    exec1(conn, "INSERT INTO fruits(id,user_id,species,mom_id,dad_id,genome_json,qty,generation,days_remaining,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (uid("fruit"), player_id, mom["species"], mom["id"], dad["id"], json.dumps(child_g), qty, child_gen, days, "growing"))
    conn.close()
    return RedirectResponse(url="/breeding", status_code=303)

@router.post("/harvest_fruit")
async def harvest_fruit(request: Request, fruit_id: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()
    rows = q(conn, "SELECT * FROM fruits WHERE id=? AND user_id=?", (fruit_id, player_id))
    if not rows:
        conn.close()
        return RedirectResponse(url="/greenhouse", status_code=303)
    f = rows[0]
    if f["status"] != "ripe":
        conn.close()
        return RedirectResponse(url="/greenhouse", status_code=303)
    seed_id = uid("seed")
    parents = {"mom": f["mom_id"], "dad": f["dad_id"]}
    exec1(conn,
          "INSERT INTO seeds(id,user_id,species,genome_json,qty,generation,parents_json) VALUES(?,?,?,?,?,?,?)",
          (seed_id, player_id, f["species"], f["genome_json"], f["qty"], f["generation"], json.dumps(parents)))
    exec1(conn, "UPDATE fruits SET status='harvested' WHERE id=?", (fruit_id,))
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

# ---------- Modal Routes ----------

@router.get("/confirm_new_game", response_class=HTMLResponse)
async def confirm_new_game(_: Request):
    # Returns a small HTML fragment injected by HTMX into #modal
    return """
<div class="modal-overlay" onclick="if(event.target.classList.contains('modal-overlay')) this.innerHTML=''">
  <div class="modal">
    <h3>Start a new game?</h3>
    <p>This will <strong>clear all your plants and seeds</strong> and grant a fresh starter pack.</p>
    <div class="modal-actions">
      <form action="/new_game" method="post" style="display:inline;">
        <button class="btn danger" type="submit">Yes, wipe it</button>
      </form>
      <button class="btn" type="button"
              hx-get="/modal_clear" hx-target="#modal" hx-swap="innerHTML">Cancel</button>
    </div>
  </div>
</div>
"""

@router.get("/modal_clear", response_class=HTMLResponse)
async def modal_clear():
    # Clears the modal host div
    return ""