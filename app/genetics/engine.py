from typing import Tuple, Dict, List
import random

# Simple species growth model (same for all species for now)
GROWTH = {
    "stage_thresholds": {  # age_days at which stage starts
        "seedling": 0,
        "juvenile": 3,
        "mature": 7,
        "flowering": 9,
        "spent": 18
    },
    "fruit_days": 4  # days from pollination to ripe fruit
}

def compute_stage(age_days: int) -> str:
    t = GROWTH["stage_thresholds"]
    if age_days >= t["spent"]: return "spent"
    if age_days >= t["flowering"]: return "flowering"
    if age_days >= t["mature"]: return "mature"
    if age_days >= t["juvenile"]: return "juvenile"
    return "seedling"

def simple_tick(age_days: int, health: float) -> Tuple[int, float, str]:
    """
    Tick a plant: age + health decay + stage update.
    """
    age_days += 1
    # gentle decay; mature/flowering a tad faster
    stage = compute_stage(age_days)
    decay = 0.003 if stage in ("seedling", "juvenile") else 0.006
    health = max(0.0, min(1.0, health - decay))
    return age_days, health, stage

def recombine_genomes(mom: Dict[str, List[str]], dad: Dict[str, List[str]]) -> Dict[str, List[str]]:
    child = {}
    all_loci = set(mom.keys()) | set(dad.keys())
    for locus in all_loci:
        m_alleles = mom.get(locus) or dad.get(locus) or ["h","h"]
        d_alleles = dad.get(locus) or mom.get(locus) or ["h","h"]
        a1 = random.choice(m_alleles)
        a2 = random.choice(d_alleles)
        child[locus] = [a1, a2]
    return child