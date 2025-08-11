# app/routes/market.py
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from datetime import datetime, timedelta
import json, sqlite3, math, time
from jinja2 import TemplateNotFound
from app.utils import get_conn, genome_fingerprint, canonical_genome, render, q

router = APIRouter()

# ---------- schema / bootstrap ----------

def ensure_market_schema():
    conn = get_conn()
    c = conn.cursor()
    # listings
    c.execute("""
    CREATE TABLE IF NOT EXISTS listings(
      id TEXT PRIMARY KEY,
      seller_id TEXT,
      seeds_id TEXT,
      price REAL NOT NULL,
      qty INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      expires_at TEXT,
      is_npc INTEGER NOT NULL DEFAULT 0
    );
    """)
    # sales
    c.execute("""
    CREATE TABLE IF NOT EXISTS sales(
      id TEXT PRIMARY KEY,
      listing_id TEXT,
      buyer_id TEXT,
      qty INTEGER NOT NULL,
      price REAL NOT NULL,
      created_at TEXT NOT NULL
    );
    """)
    # wallet on players (soft currency)
    try:
        c.execute("ALTER TABLE players ADD COLUMN wallet REAL NOT NULL DEFAULT 200.0;")
    except Exception:
        pass
    # index helpers
    c.execute("CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(is_npc, expires_at);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_recent ON sales(created_at);")
    conn.commit()
    conn.close()

def now_iso():
    return datetime.utcnow().isoformat()

def uid(prefix):
    return f"{prefix}_{hex(int(time.time()*1000))[-8:]}"

# ---------- pricing helpers ----------

def recent_demand_index(conn, species: str, hours: int = 48) -> float:
    """Return a demand multiplier based on recent sales frequency for this species."""
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    rows = q(conn, """
        SELECT COUNT(*) as n, SUM(qty) as total FROM sales s
        JOIN listings l ON l.id=s.listing_id
        JOIN seeds sd ON sd.id=l.seeds_id
        WHERE s.created_at>=? AND sd.species=?;
    """, (since, species))
    n = rows[0]["n"] or 0
    total = rows[0]["total"] or 0
    # Baseline = 5 transactions or 50 seeds in window => 1.0
    mult = 0.6 + 0.4 * min(2.0, (n/5.0 + total/50.0)/2.0)  # 0.6 .. 1.0 .. 1.4
    return max(0.5, min(1.6, mult))

def difficulty_from_genome(genome: dict) -> float:
    """Heuristic: rarer colors & variegation bump price; height extremes small bump."""
    color = (genome or {}).get("c")
    if not color and "CLR" in (genome or {}):
        alleles = genome["CLR"]
        color = "green"
        if isinstance(alleles, list) and len(alleles)>=1:
            a = alleles[0]
            color = {"R":"red","P":"purple","G":"green","Y":"yellow","T":"teal"}.get(a,"green")
    color_mult = {"green":1.0, "yellow":1.05, "teal":1.08, "red":1.12, "purple":1.15, "white":1.18}.get(color,1.0)
    vv = False
    if "vv" in (genome or {}):
        vv = bool(genome["vv"]) and str(genome["vv"]).lower() not in ("0","false","none","")
    elif "VAR" in (genome or {}):
        VAR = genome["VAR"]
        vv = isinstance(VAR, list) and len(VAR)>=2 and VAR[0]=="v" and VAR[1]=="v"
    var_mult = 1.0 + (0.15 if vv else 0.0)
    # height extremes
    h = 4
    if "h" in (genome or {}):
        try: h = int(genome["h"])
        except: pass
    else:
        # count H+ alleles across H1..H4
        h = 0
        for L in ("H1","H2","H3","H4"):
            al = (genome or {}).get(L, ["h","h"])
            if isinstance(al, list) and len(al)>=2:
                h += (1 if al[0]=="H+" else 0) + (1 if al[1]=="H+" else 0)
    height_mult = 1.0 + (0.05 if h in (0,1,7,8) else 0.0)
    return color_mult * var_mult * height_mult

def stability_from_genome(genome: dict) -> float:
    """Rough % homozygous across visible loci."""
    if not genome:
        return 1.0
    loci = []
    for L in ("H1","H2","H3","H4","VAR","PAT","CLR"):
        al = genome.get(L)
        if isinstance(al, list) and len(al)>=2:
            loci.append(1.0 if al[0]==al[1] else 0.5)
    if not loci: 
        return 1.0
    return 0.8 + 0.4 * (sum(loci)/len(loci))  # 0.8 .. 1.2

def reputation_mult(seller_rows) -> float:
    """For now, all players 1.0; room to add later."""
    return 1.0

def suggested_price(conn, seed_row) -> float:
    """Base × demand × difficulty × stability × rep."""
    species = seed_row["species"]
    genome = json.loads(seed_row["genome_json"])
    base = 10.0  # soft-currency base
    demand = recent_demand_index(conn, species)
    diff = difficulty_from_genome(genome)
    stab = stability_from_genome(genome)
    rep  = 1.0
    price = base * demand * diff * stab * rep
    # round to 1 decimal
    return round(price, 1)

# ---------- NPC management ----------

def recalc_npc_listings(conn):
    """Recreate/refresh NPC listings hourly per species."""
    # last run?
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);""")
    conn.commit()
    last = q(conn, "SELECT v FROM kv WHERE k='npc_recalc_at';")
    need = True
    if last:
        try:
            t = datetime.fromisoformat(last[0]["v"])
            need = (datetime.utcnow() - t) > timedelta(hours=1)
        except:
            need = True
    if not need:
        return

    # wipe old NPC listings
    c.execute("DELETE FROM listings WHERE is_npc=1;")
    # create one per species if seeds exist anywhere (ensures market is alive)
    species_rows = q(conn, "SELECT DISTINCT species FROM seeds;")
    for row in species_rows:
        sp = row["species"]
        # pick a representative genome from any seed lot of that species (just for pricing)
        any_seed = q(conn, "SELECT * FROM seeds WHERE species=? ORDER BY qty DESC LIMIT 1;", (sp,))
        if not any_seed: 
            continue
        seed = any_seed[0]
        price = suggested_price(conn, seed)
        qty = 6 + (hash(sp) % 7)  # 6..12
        listing_id = uid("list")
        expires = (datetime.utcnow() + timedelta(hours=6)).isoformat()
        c.execute("""INSERT INTO listings(id, seller_id, seeds_id, price, qty, created_at, expires_at, is_npc)
                     VALUES(?,?,?,?,?,?,?,1);""",
                  (listing_id, "NPC", seed["id"], price, qty, now_iso(), expires))
    c.execute("INSERT OR REPLACE INTO kv(k,v) VALUES('npc_recalc_at',?);", (now_iso(),))
    conn.commit()

# ---------- routes ----------

@router.get("/market", response_class=HTMLResponse)
async def market_page(request: Request, species: str = "", trait: str = ""):
    ensure_market_schema()
    conn = get_conn()
    recalc_npc_listings(conn)

    # active listings
    where = " WHERE qty>0 "
    params = []
    if species:
        where += " AND sd.species=? "
        params.append(species)
    rows = q(conn, f"""
      SELECT l.*, sd.species, sd.generation, sd.genome_json, sd.id as seed_id
      FROM listings l
      JOIN seeds sd ON sd.id=l.seeds_id
      {where}
      ORDER BY l.is_npc DESC, l.created_at DESC;
    """, tuple(params))
    # prep display
    items = []
    for r in rows:
        genome = json.loads(r["genome_json"])
        items.append({
            "id": r["id"],
            "is_npc": bool(r["is_npc"]),
            "seller": r["seller_id"],
            "species": r["species"],
            "generation": r["generation"],
            "gfp": genome_fingerprint(genome),
            "price": r["price"],
            "qty": r["qty"],
            "seed_id": r["seeds_id"],
            "created_at": r["created_at"]
        })

    # seed lots owned by current player for quick-listing
    player = q(conn, "SELECT id, wallet FROM players ORDER BY created_at LIMIT 1;")[0]
    my_seeds = q(conn, "SELECT * FROM seeds WHERE user_id=? AND qty>0 ORDER BY created_at DESC;", (player["id"],))

    # suggested prices for each of my lots
    sugg = {}
    for s in my_seeds:
        try:
            sugg[s["id"]] = suggested_price(conn, s)
        except Exception:
            sugg[s["id"]] = 10.0

    html = render(request, "market.html", {
        "items": items,
        "my_seeds": my_seeds,
        "suggested": sugg,
        "wallet": player["wallet"],
        "species_filter": species,
    })
    conn.close()
    return html

@router.get("/wallet")
async def wallet():
    conn = get_conn()
    row = q(conn, "SELECT wallet FROM players ORDER BY created_at LIMIT 1;")[0]
    conn.close()
    return {"wallet": round(row["wallet"], 1)}

@router.post("/list")
async def list_item(seeds_id: str = Form(...), qty: int = Form(...), price: float = Form(...)):
    conn = get_conn()
    c = conn.cursor()
    player = q(conn, "SELECT * FROM players ORDER BY created_at LIMIT 1;")[0]
    seed = q(conn, "SELECT * FROM seeds WHERE id=? AND user_id=?;", (seeds_id, player["id"]))
    if not seed:
        conn.close()
        return JSONResponse({"error":"You don't own that seed lot."}, status_code=400)
    seed = seed[0]
    if qty <= 0 or qty > seed["qty"]:
        conn.close()
        return JSONResponse({"error":"Invalid quantity."}, status_code=400)

    # create listing and reserve qty (deduct immediately)
    listing_id = uid("list")
    c.execute("""INSERT INTO listings(id, seller_id, seeds_id, price, qty, created_at, expires_at, is_npc)
                 VALUES(?,?,?,?,?,?,NULL,0);""",
              (listing_id, player["id"], seeds_id, price, qty, now_iso()))
    c.execute("UPDATE seeds SET qty=qty-? WHERE id=?;", (qty, seeds_id))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/market", status_code=303)

@router.post("/buy")
async def buy(listing_id: str = Form(...), qty: int = Form(...)):
    conn = get_conn()
    c = conn.cursor()
    player = q(conn, "SELECT * FROM players ORDER BY created_at LIMIT 1;")[0]
    listing_rows = q(conn, """
      SELECT l.*, sd.species, sd.generation, sd.genome_json, sd.user_id as owner
      FROM listings l JOIN seeds sd ON sd.id=l.seeds_id
      WHERE l.id=?;
    """, (listing_id,))
    if not listing_rows:
        conn.close()
        return JSONResponse({"error":"Listing not found."}, status_code=404)
    l = listing_rows[0]
    qty = int(qty)
    if qty <= 0 or qty > l["qty"]:
        conn.close()
        return JSONResponse({"error":"Invalid qty."}, status_code=400)
    total_cost = round(l["price"] * qty, 1)

    # wallet check
    if player["wallet"] < total_cost:
        conn.close()
        return JSONResponse({"error":"Insufficient funds."}, status_code=400)

    # transfer: reduce listing qty, credit seller wallet, debit buyer wallet
    c.execute("UPDATE listings SET qty=qty-? WHERE id=?;", (qty, listing_id))
    c.execute("UPDATE players SET wallet=wallet-? WHERE id=?;", (total_cost, player["id"]))
    if not l["is_npc"]:
        c.execute("UPDATE players SET wallet=wallet+? WHERE id=?;", (total_cost, l["seller_id"]))

    # move seeds to buyer (merge by genome/species/generation)
    genome = json.loads(l["genome_json"])
    canon = json.dumps(canonical_genome(genome), sort_keys=True)
    existing = q(conn, """
      SELECT * FROM seeds WHERE user_id=? AND species=? AND generation=? AND genome_json=? LIMIT 1;
    """, (player["id"], l["species"], l["generation"], canon))
    if existing:
        c.execute("UPDATE seeds SET qty=qty+? WHERE id=?;", (qty, existing[0]["id"]))
    else:
        new_id = uid("seed")
        c.execute("""INSERT INTO seeds(id, user_id, species, generation, qty, genome_json, parents_json, created_at)
                     VALUES(?,?,?,?,?,?,?,?);""",
                  (new_id, player["id"], l["species"], l["generation"], qty, canon, json.dumps({"mom":None,"dad":None}), now_iso()))

    # record sale
    sale_id = uid("sale")
    c.execute("""INSERT INTO sales(id, listing_id, buyer_id, qty, price, created_at)
                 VALUES(?,?,?,?,?,?);""",
              (sale_id, listing_id, player["id"], qty, l["price"], now_iso()))
    conn.commit()
    conn.close()
    return RedirectResponse(url="/market", status_code=303)
