from typing import Tuple, Dict, List
import random

def simple_tick(age_days: int, health: float) -> Tuple[int, float]:
    age_days += 1
    health = max(0.0, min(1.0, health - 0.005))
    return age_days, health

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