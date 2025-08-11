# app/utils.py
import json
import hashlib
import random
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple, List

from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi import Request

# ------------------------------
# Paths / Jinja environment
# ------------------------------
ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "app" / "templates"
DB_FILE = ROOT / "game.sqlite"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ------------------------------
# DB helpers
# ------------------------------
def get_conn() -> sqlite3.Connection:
    """Open a SQLite connection with Row factory."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def q(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] | Iterable[Any] = ()) -> List[dict]:
    """Run a query and return list of dict rows."""
    cur = conn.execute(sql, tuple(params))
    rows = cur.fetchall()
    return [dict(r) for r in rows]


# ------------------------------
# Rendering helper
# ------------------------------
def render(request: Request, template_name: str, context: Dict[str, Any] | None = None) -> HTMLResponse:
    """Render a Jinja template into an HTMLResponse (adds request automatically)."""
    context = context or {}
    context["request"] = request
    return templates.TemplateResponse(template_name, context)


# ------------------------------
# ID / time helpers
# ------------------------------
def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def uid(prefix: str | None = None) -> str:
    """
    Short unique id. If prefix is given, returns <prefix>_<id>.
    Uses time (ms) + random nibble for low collision chance.
    """
    base = f"{int(time.time() * 1000):x}{random.randrange(0, 16):x}"[-8:]
    return f"{prefix}_{base}" if prefix else base


# ------------------------------
# Generation helpers
# ------------------------------
def next_generation_label(gen: int) -> str:
    """Return a short label for a generation number, e.g. G01, G12."""
    return f"G{int(gen):02d}"


def grant_starter_pack(conn: sqlite3.Connection, user_id: str) -> None:
    """Give a new player a small starter seed lot if they have none."""
    has_seeds = q(conn, "SELECT 1 FROM seeds WHERE user_id=? LIMIT 1", (user_id,))
    if has_seeds:
        return
    conn.execute(
        "INSERT INTO seeds(id,user_id,species,genome_json,qty,generation,parents_json) VALUES(?,?,?,?,?,?,?)",
        (
            uid("seed"),
            user_id,
            "starter",
            json.dumps({}),
            5,
            next_generation_label(1),
            json.dumps({"mom": None, "dad": None}),
        ),
    )
    conn.commit()


def compute_lot_qty(mom_health: float, dad_health: float, selfing: bool) -> int:
    """Compute seed lot size based on parent health and whether selfing."""
    base = random.randint(4, 10)
    vigor = (mom_health + dad_health) / 2.0
    bonus = int(vigor * 4)
    penalty = 1 if selfing else 0
    return max(2, min(24, base + bonus - penalty))


def preview_cross_stats(mom_g: dict, dad_g: dict) -> dict:
    """Return rough probabilities for traits in a cross preview."""

    def prob_dominant(mom: list[str], dad: list[str], dom: str, rec: str) -> float:
        p_cc = (mom.count(rec) / 2.0) * (dad.count(rec) / 2.0)
        return 1.0 - p_cc

    def prob_vv(mom: list[str], dad: list[str]) -> float:
        return (mom.count("v") / 2.0) * (dad.count("v") / 2.0)

    def expected_height(mom_g: dict, dad_g: dict) -> float:
        loci = ["H1", "H2", "H3", "H4"]
        mean = 0.0
        for L in loci:
            m = mom_g.get(L, ["h", "h"])
            d = dad_g.get(L, ["h", "h"])
            mean += (m.count("H+") / 2.0) + (d.count("H+") / 2.0)
        return mean

    loci = set(mom_g.keys()) | set(dad_g.keys())
    fixed = 0
    for L in loci:
        m = mom_g.get(L, [])
        d = dad_g.get(L, [])
        if len(m) == 2 and len(d) == 2 and m[0] == m[1] == d[0] == d[1]:
            fixed += 1

    return {
        "p_colored": prob_dominant(mom_g.get("C", ["c", "c"]), dad_g.get("C", ["c", "c"]), "C", "c"),
        "p_variegated": prob_vv(mom_g.get("VAR", ["V", "V"]), dad_g.get("VAR", ["V", "V"])),
        "h_mean": expected_height(mom_g, dad_g),
        "stability": (fixed / len(loci)) if loci else 0.0,
    }


def ensure_slots(conn: sqlite3.Connection, user_id: str, n: int = 6) -> None:
    """Ensure a player has at least n greenhouse slots."""
    rows = q(conn, "SELECT COUNT(*) AS c FROM slots WHERE user_id=?", (user_id,))
    current = rows[0]["c"] if rows else 0
    if current >= n:
        return
    for _ in range(n - current):
        conn.execute(
            "INSERT INTO slots(id,user_id,soil,light,water,temp) VALUES(?,?,?,?,?,?)",
            (uid("slot"), user_id, "loam", "med", "ok", "warm"),
        )
    conn.commit()


def bind_plant_to_slot(conn: sqlite3.Connection, slot_id: str, plant_id: str) -> None:
    """Attach a plant to a greenhouse slot."""
    conn.execute("UPDATE slots SET plant_id=? WHERE id=?", (plant_id, slot_id))
    conn.commit()


def get_env_for_plant(conn: sqlite3.Connection, user_id: str, plant_id: str) -> dict:
    """Return environment settings for a player's plant."""
    rows = q(conn, "SELECT soil, light, water, temp FROM slots WHERE user_id=? AND plant_id=?", (user_id, plant_id))
    if not rows:
        return {"soil": "loam", "light": "med", "water": "ok", "temp": "warm"}
    r = rows[0]
    return {"soil": r["soil"], "light": r["light"], "water": r["water"], "temp": r["temp"]}


# ------------------------------
# Genome canon & fingerprint
# ------------------------------
def _canonicalize(value: Any) -> Any:
    """
    Recursively sort dict keys; sort lists when elements are simple (str/int).
    Keeps structure stable so two equivalent genomes hash the same.
    """
    if isinstance(value, dict):
        return {k: _canonicalize(value[k]) for k in sorted(value.keys())}
    if isinstance(value, list):
        if all(isinstance(x, (str, int, float)) for x in value):
            try:
                return sorted(value)
            except Exception:
                return [_canonicalize(x) for x in value]
        return [_canonicalize(x) for x in value]
    return value


def canonical_genome(genome: Dict[str, Any] | str) -> Dict[str, Any]:
    """
    Return a canonicalized genome dict (NOT a JSON string).
    - Sorts all keys
    - Sorts allele lists when items are scalar
    """
    if genome is None:
        return {}
    if isinstance(genome, str):
        try:
            genome = json.loads(genome)
        except Exception:
            return {"RAW": str(genome)}
    return _canonicalize(genome)


def genome_fingerprint(genome: Dict[str, Any] | str, length: int = 6) -> str:
    """
    Stable short hash (hex) of the canonical genome.
    Default length: 6 chars (shown as 'geno abc123' in UI).
    """
    canon = canonical_genome(genome)
    data = json.dumps(canon, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha1(data).hexdigest()[:length]


# ------------------------------
# Phenotype expression (for UI & gameplay)
# ------------------------------
# Color dominance mapping for CLR locus
_DOM_ORDER = {"R": 5, "P": 4, "G": 3, "Y": 2, "T": 1}
_CLR_TO_NAME = {"R": "red", "P": "purple", "G": "green", "Y": "yellow", "T": "teal"}

def _resolve_color_name(genome: Dict[str, Any]) -> str:
    # direct simplified key
    c = (genome or {}).get("c")
    if isinstance(c, str):
        return c
    # locus-based
    clr = (genome or {}).get("CLR")
    if isinstance(clr, list) and len(clr) >= 1:
        a = clr[0]
        b = clr[1] if len(clr) > 1 else a
        code = a if _DOM_ORDER.get(a, 3) >= _DOM_ORDER.get(b, 3) else b
        return _CLR_TO_NAME.get(code, "green")
    return "green"

def _resolve_variegation(genome: Dict[str, Any]) -> bool:
    if "vv" in (genome or {}):
        v = genome.get("vv")
        return bool(v) and str(v).lower() not in ("0", "false", "none", "")
    VAR = (genome or {}).get("VAR")
    if isinstance(VAR, list) and len(VAR) >= 2:
        # recessive vv
        a, b = VAR[0], VAR[1]
        return str(a).lower() == "v" and str(b).lower() == "v"
    return False

def _resolve_height_score(genome: Dict[str, Any]) -> int:
    if "h" in (genome or {}):
        try:
            return max(0, min(8, int(genome.get("h", 4))))
        except Exception:
            return 4
    # derive from H1..H4
    score = 0
    for L in ("H1", "H2", "H3", "H4"):
        al = (genome or {}).get(L, ["h", "h"])
        if isinstance(al, list) and len(al) >= 2:
            score += (1 if al[0] == "H+" else 0) + (1 if al[1] == "H+" else 0)
    return max(0, min(8, score))

def _resolve_leafiness(genome: Dict[str, Any], height_score: int) -> int:
    if "leaves" in (genome or {}):
        try:
            return max(1, min(5, int(genome["leaves"])))
        except Exception:
            pass
    # optional ML locus boosts tiers
    ML = (genome or {}).get("ML")
    bonus = 0
    if isinstance(ML, list) and len(ML) >= 2:
        bonus = (1 if ML[0] == "L+" else 0) + (1 if ML[1] == "L+" else 0)
    base = 1 + (height_score // 2)  # 0..8 -> 1..5-ish
    return max(1, min(5, base + bonus))

def express_phenotype(genome: Dict[str, Any] | str) -> Dict[str, Any]:
    """
    Convert any stored genome (dict or JSON string) into a compact phenotype dict
    used by UI & systems:
      {
        "color_name": "green|red|yellow|purple|teal|white",
        "variegated": bool,
        "height_score": 0..8,
        "leaf_tiers": 1..5,
        # convenience mirrors:
        "c": <color_name>, "vv": bool, "h": int, "leaves": int,
        "gfp": "abcdef"  # fingerprint of canonical genome
      }
    """
    if isinstance(genome, str):
        try:
            genome = json.loads(genome)
        except Exception:
            genome = {"RAW": genome}

    color_name = _resolve_color_name(genome)
    vv = _resolve_variegation(genome)
    h = _resolve_height_score(genome)
    leaves = _resolve_leafiness(genome, h)
    gfp = genome_fingerprint(genome)

    return {
        "color_name": color_name,
        "variegated": vv,
        "height_score": h,
        "leaf_tiers": leaves,
        "c": color_name,
        "vv": vv,
        "h": h,
        "leaves": leaves,
        "gfp": gfp,
    }


# ------------------------------
# Tiny util: safe int
# ------------------------------
def clamp_int(n: Any, lo: int, hi: int, default: int) -> int:
    try:
        v = int(n)
    except Exception:
        return default
    return max(lo, min(hi, v))
