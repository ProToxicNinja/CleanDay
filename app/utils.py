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
