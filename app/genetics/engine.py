from typing import Tuple, Dict, List
import random

# Base growth model (same for all species for now)
BASE_THRESHOLDS = {
    "seedling": 0,
    "juvenile": 3,
    "mature": 7,
    "flowering": 9,
    "spent": 18
}
BASE_FRUIT_DAYS = 4

def thresholds_with_env(env: Dict[str, str]) -> Dict[str, int]:
    """
    Adjust stage thresholds based on environment.
    Negative offset = reaches stage earlier (faster).
    """
    soil, light, water, temp = env["soil"], env["light"], env["water"], env["temp"]
    offs = {"juvenile": 0, "mature": 0, "flowering": 0, "spent": 0}

    # Soil
    if soil == "sand": offs["flowering"] -= 1  # faster to flower
    if soil == "clay": offs["mature"] -= 1; offs["flowering"] += 1  # stronger but slower to flower

    # Light
    if light == "low": offs["mature"] += 1; offs["flowering"] += 1
    if light == "high": offs["mature"] -= 1; offs["flowering"] -= 1

    # Water
    if water == "under": offs["mature"] += 1; offs["flowering"] += 1
    if water == "over": offs["mature"] += 0; offs["flowering"] += 0  # small/no change

    # Temp
    if temp == "cool": offs["flowering"] += 1
    if temp == "warm": offs["flowering"] -= 1

    # Build adjusted thresholds, never less than previous stage +1
    t = dict(BASE_THRESHOLDS)
    t["juvenile"] = max(1, t["juvenile"] + offs["juvenile"])
    t["mature"]   = max(t["juvenile"]+1, t["mature"] + offs["mature"])
    t["flowering"]= max(t["mature"]+1,  t["flowering"] + offs["flowering"])
    t["spent"]    = max(t["flowering"]+2, t["spent"] + offs["spent"])
    return t

def compute_stage(age_days: int, env: Dict[str, str] | None = None) -> str:
    T = thresholds_with_env(env) if env else BASE_THRESHOLDS
    if age_days >= T["spent"]: return "spent"
    if age_days >= T["flowering"]: return "flowering"
    if age_days >= T["mature"]: return "mature"
    if age_days >= T["juvenile"]: return "juvenile"
    return "seedling"

def health_decay(stage: str, env: Dict[str, str]) -> float:
    decay = 0.003 if stage in ("seedling","juvenile") else 0.006
    # Soil: clay/loam support health; sand a bit harsher
    if env["soil"] == "clay": decay -= 0.001
    if env["soil"] == "sand": decay += 0.001
    # Water: under hurts; over slightly hurts
    if env["water"] == "under": decay += 0.003
    if env["water"] == "over": decay += 0.001
    # Temp: cool helps health a touch
    if env["temp"] == "cool": decay -= 0.001
    return max(0.001, decay)

def fruit_days_with_env(env: Dict[str, str]) -> int:
    d = BASE_FRUIT_DAYS
    if env["light"] == "high": d -= 1
    if env["temp"] == "warm": d -= 1
    if env["water"] == "under": d += 1
    return max(2, d)

def simple_tick(age_days: int, health: float, env: Dict[str, str]) -> Tuple[int, float, str]:
    """Advance one day: apply env-influenced stage + health."""
    age_days += 1
    stage = compute_stage(age_days, env)
    health = max(0.0, min(1.0, health - health_decay(stage, env)))
    return age_days, health, stage

def recombine_genomes(mom: Dict[str, List[str]], dad: Dict[str, List[str]]) -> Dict[str, List[str]]:
    child = {}
    all_loci = set(mom.keys()) | set(dad.keys())
    for locus in all_loci:
        m_alleles = mom.get(locus) or dad.get(locus) or ["h","h"]
        d_alleles = dad.get(locus) or mom.get(locus) or ["h","h"]
        child[locus] = [random.choice(m_alleles), random.choice(d_alleles)]
    return child

# Legacy compatibility for GROWTH references
GROWTH = {
    "fruit_days": BASE_FRUIT_DAYS,
    "stage_thresholds": BASE_THRESHOLDS
}