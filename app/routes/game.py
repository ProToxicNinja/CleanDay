import os
import json
import hashlib
from collections import OrderedDict
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response, PlainTextResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.db import get_conn, q, exec1, DB_PATH, init_db
from app.utils import (
    uid, express_phenotype, next_generation_label, grant_starter_pack,
    compute_lot_qty, preview_cross_stats,
    ensure_slots, bind_plant_to_slot,
    get_env_for_plant, genome_fingerprint
)
from app.genetics.engine import simple_tick, recombine_genomes, fruit_days_with_env

# ---- SAFE SPRITE IMPORT ----
try:
    from app.sprites import render_plant_svg, render_seed_svg
except Exception:
    def render_plant_svg(genome, stage, pid):
        return """<svg xmlns='http://www.w3.org/2000/svg' width='100' height='90'>
          <rect x='8' y='74' width='84' height='12' rx='4' fill='#3a3f55'/>
          <circle cx='50' cy='40' r='12' fill='#9aa0ae' />
        </svg>"""
    def render_seed_svg(species):
        return """<svg xmlns='http://www.w3.org/2000/svg' width='64' height='42'>
          <rect x='1' y='1' width='62' height='40' rx='8' fill='#111424' stroke='#2a2f45'/>
          <ellipse cx='32' cy='21' rx='10' ry='14' fill='#6b5238' stroke='#2f1f12'/>
        </svg>"""

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

# ---------- Helpers / Debug ----------
def _route_list(app) -> str:
    lines = []
    for route in app.routes:
        try:
            methods = ",".join(route.methods) if hasattr(route, "methods") else "-"
            lines.append(f"{methods:10s} {route.path}")
        except Exception:
            pass
    return "\n".join(sorted(lines))

@router.get("/routes")
async def list_routes(_: Request):
    from app.main import app
    return PlainTextResponse(_route_list(app))

@router.get("/debug/plant/{plant_id}")
async def debug_plant(plant_id: str):
    """Quick JSON peek at a plant’s current fields (for troubleshooting)."""
    conn = get_conn()
    rows = q(conn, "SELECT id, species, generation, age_days, health, stage, updated_at, genome_json FROM plants WHERE id=?", (plant_id,))
    conn.close()
    if not rows:
        return JSONResponse({"error":"not found"}, status_code=404)
    r = rows[0]
    return JSONResponse({
        "id": r["id"], "species": r["species"], "generation": r["generation"],
        "age_days": r["age_days"], "health": r["health"], "stage": r["stage"],
        "updated_at": r["updated_at"], "fingerprint": genome_fingerprint(json.loads(r["genome_json"]))
    })

# ---------- Root redirect ----------
@router.get("/", response_class=HTMLResponse)
async def root_redirect(_: Request):
    return RedirectResponse(url="/greenhouse", status_code=307)

# ---------- SPRITES ----------
@router.get("/sprite/plant/{plant_id}.svg")
async def sprite_for_plant(plant_id: str):
    conn = get_conn()
    rows = q(conn, "SELECT genome_json, stage, id, health, updated_at FROM plants WHERE id=?", (plant_id,))
    conn.close()
    if not rows:
        return Response(content="<svg/>", media_type="image/svg+xml",
                        status_code=404, headers={"Cache-Control": "no-store"})
    row = rows[0]
    genome = json.loads(row["genome_json"])
    stage = (row["stage"] or "seedling")
    svg = render_plant_svg(genome, stage, row["id"])
    etag = hashlib.sha1(f"{row['id']}-{stage}-{row['health']:.3f}-{row['updated_at']}".encode()).hexdigest()
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "no-store, max-age=0",
            "ETag": etag
        }
    )

@router.get("/sprite/seed/{species}.svg")
async def sprite_for_seed(species: str):
    return Response(content=render_seed_svg(species), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=3600"})

# ---------- Screens ----------
@router.get("/greenhouse", response_class=HTMLResponse)
async def greenhouse(request: Request):
    player_id = request.state.player_id
    conn = get_conn()
    ensure_slots(conn, player_id, 6)

    # Day counter column
    try:
        exec1(conn, "ALTER TABLE users ADD COLUMN day INTEGER DEFAULT 1")
    except Exception:
        pass
    day_row = q(conn, "SELECT day FROM users WHERE id=?", (player_id,))
    day = int(day_row[0]["day"] or 1) if day_row else 1

    # Slots + attach plant VM if present (include updated_at for cache-busting)
    slot_rows = q(conn, "SELECT * FROM slots WHERE user_id=? ORDER BY created_at ASC", (player_id,))
    slots = []
    for s in slot_rows:
        plant_vm = None
        if s["plant_id"]:
            prow = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (s["plant_id"], player_id))
            if prow:
                p = prow[0]
                genome = json.loads(p["genome_json"])
                pheno = express_phenotype(genome)
                plant_vm = {
                    "id": p["id"],
                    "name": p["name"] or "",
                    "species": p["species"],
                    "generation": p["generation"],
                    "stage": p["stage"],
                    "health": round(p["health"], 3),
                    "updated_at": p["updated_at"],
                    "gfp": genome_fingerprint(genome),
                    "appearance": pheno["appearance"],
                    "height_score": pheno["height_score"],
                }
        slots.append({"id": s["id"], "plant": plant_vm, "soil": s["soil"], "light": s["light"], "water": s["water"], "temp": s["temp"]})

    fruits = q(conn, "SELECT * FROM fruits  WHERE user_id=? ORDER BY created_at DESC", (player_id,))
    conn.close()

    return templates.TemplateResponse("greenhouse.html", {
        "request": request, "slots": slots, "fruits": fruits, "day": day
    })

@router.get("/slot_modal/{slot_id}", response_class=HTMLResponse)
async def slot_modal(request: Request, slot_id: str):
    player_id = request.state.player_id
    conn = get_conn()
    rows = q(conn, "SELECT * FROM slots WHERE id=? AND user_id=?", (slot_id, player_id))
    if not rows:
        conn.close()
        return HTMLResponse("<div class='card'>Slot not found.</div>", status_code=404)
    s = rows[0]

    plant_vm = None
    if s["plant_id"]:
        prow = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (s["plant_id"], player_id))
        if prow:
            p = prow[0]
            genome = json.loads(p["genome_json"])
            pheno = express_phenotype(genome)
            plant_vm = {
                "id": p["id"],
                "name": p["name"] or "",
                "species": p["species"],
                "generation": p["generation"],
                "stage": p["stage"],
                "health": round(p["health"], 3),
                "updated_at": p["updated_at"],
                "gfp": genome_fingerprint(genome),
                "appearance": pheno["appearance"],
                "height_score": pheno["height_score"],
            }

    seed_rows = q(conn, "SELECT id,species,genome_json,qty,generation FROM seeds WHERE user_id=? AND qty>0 ORDER BY created_at DESC", (player_id,))
    seeds = []
    for r in seed_rows:
        try:
            g = json.loads(r["genome_json"])
        except Exception:
            g = r["genome_json"]
        seeds.append({
            "id": r["id"], "species": r["species"], "qty": r["qty"],
            "generation": r["generation"], "gfp": genome_fingerprint(g),
        })

    conn.close()
    slot_vm = {"id": s["id"], "plant": plant_vm, "soil": s["soil"], "light": s["light"], "water": s["water"], "temp": s["temp"]}
    return templates.TemplateResponse("partials/slot_modal.html", {
        "request": request, "slot": slot_vm, "seeds": seeds
    })

# ---------- Slot & Plant actions ----------
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
async def plant_seed(request: Request, seed_id: str = Form(...), slot_id: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()

    lot_rows = q(conn, "SELECT * FROM seeds WHERE id=? AND user_id=?", (seed_id, player_id))
    if not lot_rows:
        conn.close(); return RedirectResponse(url="/greenhouse", status_code=303)
    lot = lot_rows[0]
    if lot["qty"] <= 0:
        conn.close(); return RedirectResponse(url="/greenhouse", status_code=303)

    slot_rows = q(conn, "SELECT * FROM slots WHERE id=? AND user_id=?", (slot_id, player_id))
    if not slot_rows:
        conn.close(); return RedirectResponse(url="/greenhouse", status_code=303)
    slot = slot_rows[0]
    if slot["plant_id"]:
        conn.close(); return RedirectResponse(url="/greenhouse", status_code=303)

    exec1(conn, "UPDATE seeds SET qty=? WHERE id=?", (lot["qty"] - 1, seed_id))
    pid = uid("plant")
    exec1(conn, """
        INSERT INTO plants(id,user_id,species,genome_json,age_days,health,generation,stage,can_breed,name)
        VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (pid, player_id, lot["species"], lot["genome_json"], 0, 1.0, lot["generation"], "seedling", 1, None))
    bind_plant_to_slot(conn, slot["id"], pid)
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

@router.post("/rename_plant")
async def rename_plant(request: Request, plant_id: str = Form(...), name: str = Form(...)):
    player_id = request.state.player_id
    name = (name or "").strip()[:40]
    conn = get_conn()
    exec1(conn, "UPDATE plants SET name=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?", (name or None, plant_id, player_id))
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

@router.post("/cull_plant")
async def cull_plant(request: Request, plant_id: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()
    exec1(conn, "UPDATE slots SET plant_id=NULL WHERE user_id=? AND plant_id=?", (player_id, plant_id))
    exec1(conn, "DELETE FROM plants WHERE user_id=? AND id=?", (player_id, plant_id))
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

# ---------- Seeds ----------
@router.get("/seeds", response_class=HTMLResponse)
async def seeds_index(request: Request):
    player_id = request.state.player_id
    conn = get_conn()
    seeds  = q(conn, "SELECT * FROM seeds WHERE user_id=? ORDER BY created_at DESC", (player_id,))
    conn.close()
    seeds_vm = []
    for s in seeds:
        try:
            g = json.loads(s["genome_json"])
        except Exception:
            g = s["genome_json"]
        seeds_vm.append({**dict(s), "fingerprint": genome_fingerprint(g)})
    err = request.query_params.get("err")
    return templates.TemplateResponse("seeds.html", {
        "request": request, "seeds": seeds_vm, "err": err
    })

@router.get("/seed/{seed_id}", response_class=HTMLResponse)
async def seed_detail(request: Request, seed_id: str):
    player_id = request.state.player_id
    conn = get_conn()
    rows = q(conn, "SELECT * FROM seeds WHERE id=? AND user_id=?", (seed_id, player_id))
    conn.close()
    if not rows:
        return HTMLResponse("<div class='card'>Seed not found.</div>", status_code=404)
    s = rows[0]
    genome = json.loads(s["genome_json"])
    parents = json.loads(s["parents_json"] or "{}") if s["parents_json"] else {}
    return templates.TemplateResponse("seed_detail.html", {
        "request": request, "seed": s, "genome": genome, "parents": parents
    })

@router.post("/delete_seed")
async def delete_seed(request: Request, seed_id: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()
    rows = q(conn, "SELECT qty FROM seeds WHERE id=? AND user_id=?", (seed_id, player_id))
    if not rows:
        conn.close(); return RedirectResponse(url="/seeds?err=notfound", status_code=303)
    qty = int(rows[0]["qty"])
    if qty > 0:
        conn.close(); return RedirectResponse(url="/seeds?err=nonempty", status_code=303)
    exec1(conn, "DELETE FROM seeds WHERE id=? AND user_id=?", (seed_id, player_id))
    conn.close()
    return RedirectResponse(url="/seeds", status_code=303)

# ---------- Day tick ----------
@router.post("/tick")
async def tick(request: Request):
    player_id = request.state.player_id
    conn = get_conn()

    # Plants (env-aware, enforce can_breed lock)
    plants = q(conn, "SELECT id, age_days, health, can_breed FROM plants WHERE user_id=?", (player_id,))
    for p in plants:
        env = get_env_for_plant(conn, player_id, p["id"])
        new_age, new_health, new_stage = simple_tick(p["age_days"], p["health"], env)
        if int(p["can_breed"]) == 0 and new_stage == "flowering":
            new_stage = "spent"
        exec1(conn, "UPDATE plants SET age_days=?, health=?, stage=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
              (new_age, new_health, new_stage, p["id"]))

    # Fruits (ripen daily)
    fruits = q(conn, "SELECT * FROM fruits WHERE user_id=? AND status='growing'", (player_id,))
    for f in fruits:
        remain = int(f["days_remaining"]) - 1
        status = "ripe" if remain <= 0 else "growing"
        exec1(conn, "UPDATE fruits SET days_remaining=?, status=? WHERE id=?",
              (max(0, remain), status, f["id"]))

    # Increment Day counter
    exec1(conn, "UPDATE users SET day = COALESCE(day,1) + 1 WHERE id=?", (player_id,))

    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

# ---------- New game ----------
@router.post("/new_game")
async def new_game(request: Request):
    player_id = request.state.player_id
    conn = get_conn()
    for table in ("plants","seeds","fruits","slots"):
        exec1(conn, f"DELETE FROM {table} WHERE user_id=?", (player_id,))
    ensure_slots(conn, player_id, 6)
    grant_starter_pack(conn, player_id)
    try:
        exec1(conn, "ALTER TABLE users ADD COLUMN day INTEGER DEFAULT 1")
    except Exception:
        pass
    exec1(conn, "UPDATE users SET day=1 WHERE id=?", (player_id,))
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

# ---------- Breeding (unchanged except for imports) ----------
_PREVIEW_CACHE_MAX = 100
_PREVIEW_CACHE: "OrderedDict[str, str]" = OrderedDict()

def _preview_key(mom_id: str, dad_id: str, mom_g: dict, dad_g: dict) -> str:
    h = hashlib.sha256()
    h.update(mom_id.encode()); h.update(dad_id.encode())
    h.update(json.dumps(mom_g, sort_keys=True).encode())
    h.update(json.dumps(dad_g, sort_keys=True).encode())
    return h.hexdigest()

def _preview_cache_get(key: str):
    if key in _PREVIEW_CACHE:
        html = _PREVIEW_CACHE.pop(key)
        _PREVIEW_CACHE[key] = html
        return html
    return None

def _preview_cache_set(key: str, html: str):
    _PREVIEW_CACHE[key] = html
    _PREVIEW_CACHE.move_to_end(key)
    while len(_PREVIEW_CACHE) > _PREVIEW_CACHE_MAX:
        _PREVIEW_CACHE.popitem(last=False)

@router.get("/breeding", response_class=HTMLResponse)
async def breeding_room(request: Request):
    player_id = request.state.player_id
    conn = get_conn()

    rows = q(conn, "SELECT * FROM plants WHERE user_id=? ORDER BY created_at DESC", (player_id,))
    cards = []
    for row in rows:
        genome = json.loads(row["genome_json"])
        pheno = express_phenotype(genome)
        can_breed_val = int(row["can_breed"]) if row["can_breed"] is not None else 0
        stage_val = (row["stage"] or "").strip().lower()
        eligible = (stage_val == "flowering" and can_breed_val == 1)
        cards.append({
            "id": row["id"], "species": row["species"], "generation": row["generation"],
            "age_days": row["age_days"], "stage": row["stage"],
            "appearance": pheno["appearance"], "height_score": pheno["height_score"],
            "can_breed": can_breed_val, "eligible": eligible,
            "gfp": genome_fingerprint(genome),
            "name": row["name"] or ""
        })

    fruits = q(conn, "SELECT * FROM fruits WHERE user_id=? ORDER BY created_at DESC LIMIT 20", (player_id,))
    conn.close()

    err = request.query_params.get("err")
    return templates.TemplateResponse("breeding.html", {
        "request": request, "plants": cards, "fruits": fruits, "err": err
    })

@router.post("/preview_cross", response_class=HTMLResponse)
async def preview_cross(request: Request, mom_id: str = Form(...), dad_id: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()
    mom = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (mom_id, player_id))
    dad = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (dad_id, player_id))
    if not mom or not dad:
        conn.close(); return HTMLResponse("<div class='muted'>Select two plants.</div>")

    mom, dad = mom[0], dad[0]

    if int(mom["can_breed"]) == 0 or int(dad["can_breed"]) == 0 or mom["stage"] != "flowering" or dad["stage"] != "flowering":
        conn.close(); return HTMLResponse("<div class='muted'>Both parents must be <strong>flowering</strong> and unused this cycle.</div>")

    mom_g = json.loads(mom["genome_json"]); dad_g = json.loads(dad["genome_json"])
    key = _preview_key(mom["id"], dad["id"], mom_g, dad_g)
    cached = _preview_cache_get(key)
    if cached:
        conn.close()
        return HTMLResponse(cached)

    stats = preview_cross_stats(mom_g, dad_g)
    html = f"""
<div class="card" style="margin-top:8px;">
  <strong>Preview</strong>
  <div class="muted">Deterministic preview (includes mutation effects).</div>
  <ul>
    <li>Likely color: <strong>{stats['top_color']}</strong> ({round(stats['p_top_color']*100)}%)</li>
    <li>Non-green chance: <strong>{round(stats['p_colored']*100)}%</strong></li>
    <li>Variegation (vv): <strong>{round(stats['p_variegated']*100)}%</strong></li>
    <li>Expected height score: <strong>{stats['h_mean']:.1f}</strong> / 8</li>
    <li>Stability (fixed loci): <strong>{round(stats['stability']*100)}%</strong></li>
  </ul>
  <div class="muted" style="margin-top:6px;">
    Mutation influence (in preview sample):
    color changed by mutation <strong>{round(stats['p_color_changed_by_mut']*100)}%</strong>,
    any mutation <strong>{round(stats['p_any_mutation']*100)}%</strong>.
  </div>
</div>
"""
    _preview_cache_set(key, html)
    conn.close()
    return HTMLResponse(html)

@router.post("/pollinate")
async def pollinate(request: Request, mom_id: str = Form(...), dad_id: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()

    moms = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (mom_id, player_id))
    dads = q(conn, "SELECT * FROM plants WHERE id=? AND user_id=?", (dad_id, player_id))
    if not moms or not dads:
        conn.close(); return RedirectResponse(url="/breeding?err=notfound", status_code=303)

    mom = moms[0]; dad = dads[0]
    if mom["species"] != dad["species"]:
        conn.close(); return RedirectResponse(url="/breeding?err=species", status_code=303)
    if (mom["stage"] != "flowering" or dad["stage"] != "flowering" or
        int(mom["can_breed"]) == 0 or int(dad["can_breed"]) == 0):
        conn.close(); return RedirectResponse(url="/breeding?err=stage", status_code=303)

    mom_g = json.loads(mom["genome_json"]); dad_g = json.loads(dad["genome_json"])
    child_g = recombine_genomes(mom_g, dad_g)
    try:
        g_m = int(str(mom["generation"])[1:]) if mom["generation"] else 1
        g_d = int(str(dad["generation"])[1:]) if dad["generation"] else 1
        child_gen = next_generation_label(max(g_m, g_d) + 1)
    except Exception:
        child_gen = next_generation_label(1)
    qty = compute_lot_qty(float(mom["health"]), float(dad["health"]), mom["id"] == dad["id"])

    env = get_env_for_plant(conn, player_id, mom["id"])
    days = fruit_days_with_env(env)

    exec1(conn, "INSERT INTO fruits(id,user_id,species,mom_id,dad_id,genome_json,qty,generation,days_remaining,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
          (uid("fruit"), player_id, mom["species"], mom["id"], dad["id"], json.dumps(child_g), qty, child_gen, days, "growing"))

    exec1(conn, "UPDATE plants SET stage='spent', can_breed=0, updated_at=CURRENT_TIMESTAMP WHERE id IN (?,?) AND user_id=?", (mom["id"], dad["id"], player_id))
    conn.close()
    return RedirectResponse(url="/breeding", status_code=303)

@router.post("/harvest_fruit")
async def harvest_fruit(request: Request, fruit_id: str = Form(...)):
    player_id = request.state.player_id
    conn = get_conn()
    rows = q(conn, "SELECT * FROM fruits WHERE id=? AND user_id=?", (fruit_id, player_id))
    if not rows:
        conn.close(); return RedirectResponse(url="/greenhouse", status_code=303)
    f = rows[0]
    if f["status"] != "ripe":
        conn.close(); return RedirectResponse(url="/greenhouse", status_code=303)

    species = f["species"]; generation = f["generation"]; genome_json = f["genome_json"]
    qty = int(f["qty"]); parents = json.dumps({"mom": f["mom_id"], "dad": f["dad_id"]})

    existing = q(conn, "SELECT id, qty FROM seeds WHERE user_id=? AND species=? AND generation=? AND genome_json=? LIMIT 1",
                 (player_id, species, generation, genome_json))
    if existing:
        lot = existing[0]
        new_qty = int(lot["qty"]) + qty
        exec1(conn, "UPDATE seeds SET qty=? WHERE id=?", (new_qty, lot["id"]))
    else:
        exec1(conn, "INSERT INTO seeds(id,user_id,species,genome_json,qty,generation,parents_json) VALUES(?,?,?,?,?,?,?)",
              (uid("seed"), player_id, species, genome_json, qty, generation, parents))

    exec1(conn, "UPDATE fruits SET status='harvested' WHERE id=?", (fruit_id,))
    conn.close()
    return RedirectResponse(url="/greenhouse", status_code=303)

# ---------- Admin ----------
@router.get("/admin", response_class=HTMLResponse)
async def admin_page(_: Request):
    return """
<!doctype html><html><head><meta charset="utf-8"><title>Admin</title>
<link rel="stylesheet" href="/static/styles.css"></head><body>
  <main class="container">
    <div class="card">
      <h2>Admin</h2>
      <p class="muted">Delete the local SQLite DB and reset state.</p>
      <form action="/admin/nuke_db" method="post" onsubmit="return confirm('Delete game.sqlite and reset?');">
        <button class="btn danger" type="submit">Nuke DB</button>
      </form>
      <p style="margin-top:10px;"><a class="link" href="/greenhouse">← Back to Greenhouse</a></p>
    </div>
  </main>
</body></html>
"""

@router.post("/admin/nuke_db")
async def admin_nuke_db(_: Request):
    try:
        if DB_PATH.exists():
            os.remove(DB_PATH)
    except Exception:
        pass
    init_db()
    resp = RedirectResponse(url="/greenhouse", status_code=303)
    resp.delete_cookie("player_id")
    return resp
