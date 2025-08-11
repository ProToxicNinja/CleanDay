import json, random, hashlib
from typing import Dict, Tuple
from collections import Counter

# --------------------------
# Helpers / constants
# --------------------------
def _hash_int(s: str) -> int:
    return int(hashlib.sha256(s.encode("utf-8")).hexdigest()[:8], 16)

CLR_ALLELES = ["R","P","G","Y","T"]
DOM_ORDER = {"R": 5, "P": 4, "G": 3, "Y": 2, "T": 1}
CODE_TO_NAME = {"R":"red","P":"purple","G":"green","Y":"yellow","T":"teal"}

MUT_COLOR = 0.02  # per-locus
MUT_VAR   = 0.02
MUT_PAT   = 0.02

# --------------------------
# Growth model (env-aware)
# --------------------------
def simple_tick(age_days: int, health: float, env: Dict) -> Tuple[int, float, str]:
    age = age_days + 1
    if age < 5: stage = "seedling"
    elif age < 12: stage = "juvenile"
    elif age < 18: stage = "mature"
    elif age < 26: stage = "flowering"
    else: stage = "spent"

    if env.get("soil") == "sand":  health *= 0.995
    elif env.get("soil") == "clay": health *= 0.992
    if env.get("water") == "under": health *= 0.992
    elif env.get("water") == "over": health *= 0.990

    health = max(0.1, min(1.0, health))
    return int(age), float(health), stage

# --------------------------
# Recombination
# --------------------------
def _pick_from_pair(rng: random.Random, pair):
    return pair[rng.randrange(2)]

def _dominant_color_code(a: str, b: str) -> str:
    ra, rb = DOM_ORDER.get(a,3), DOM_ORDER.get(b,3)
    return a if ra >= rb else b

def recombine_genomes(mom: Dict, dad: Dict, rng: random.Random | None = None, allow_mut: bool = True) -> Dict:
    """
    Mendelian recombination with optional mutation.
    - rng: pass Random for deterministic outcomes; fallback to global random.
    - allow_mut: if False, skip mutations.
    """
    rng = rng or random
    loci = set(mom.keys()) | set(dad.keys())
    child: Dict = {}
    for L in loci:
        ma = mom.get(L, ["h","h"])
        da = dad.get(L, ["h","h"])
        child[L] = [_pick_from_pair(rng, ma), _pick_from_pair(rng, da)]
    for L in ("H1","H2","H3","H4"):
        child.setdefault(L, ["h","h"])

    if not allow_mut:
        return child

    # color
    if rng.random() < MUT_COLOR:
        child.setdefault("CLR", ["G","G"])
        child["CLR"][rng.randrange(2)] = rng.choice(CLR_ALLELES)
    # variegation
    if rng.random() < MUT_VAR:
        child.setdefault("VAR", ["V","V"])
        i = rng.randrange(2)
        child["VAR"][i] = "v" if child["VAR"][i] == "V" else "V"
    # pattern
    if rng.random() < MUT_PAT:
        child.setdefault("PAT", ["N","N"])
        i = rng.randrange(2)
        child["PAT"][i] = "s" if child["PAT"][i] == "N" else "N"

    return child

# --------------------------
# Fruit timing
# --------------------------
def fruit_days_with_env(env: Dict) -> int:
    base = 6
    if env.get("light") == "high": base -= 1
    if env.get("soil") == "clay": base += 1
    return max(3, base)

# --------------------------
# Preview (deterministic, WITH mutations)
# --------------------------
def preview_cross_stats(mom_g: Dict, dad_g: Dict, trials: int = 400) -> Dict:
    """
    Deterministic Monte Carlo preview:
    - Seeded by parents, so same pair => same results.
    - Includes mutation effects, but deterministically (no UI flicker).
    Also reports how often mutations changed color / VAR / PAT in the sample.
    """
    seed_src = json.dumps({"m": mom_g, "d": dad_g}, sort_keys=True)
    rng = random.Random(_hash_int(seed_src))

    color_counts = Counter()
    vv_count = 0
    h_sum = 0.0
    stability_sum = 0.0

    mut_any = 0
    mut_color_changed = 0
    mut_var_changed = 0
    mut_pat_changed = 0

    for _ in range(trials):
        # Step 1: base recombination (no mutation)
        base_child = recombine_genomes(mom_g, dad_g, rng=rng, allow_mut=False)

        # Keep a copy to mutate deterministically
        child = json.loads(json.dumps(base_child))

        # Apply deterministic mutations using the same rng
        color_mut = False
        var_mut = False
        pat_mut = False

        # Color mutation
        if rng.random() < MUT_COLOR:
            child.setdefault("CLR", ["G","G"])
            idx = rng.randrange(2)
            before = child["CLR"][idx]
            child["CLR"][idx] = rng.choice(CLR_ALLELES)
            color_mut = (child["CLR"][idx] != before)

        # Variegation mutation
        if rng.random() < MUT_VAR:
            child.setdefault("VAR", ["V","V"])
            idx = rng.randrange(2)
            before = child["VAR"][idx]
            child["VAR"][idx] = "v" if before == "V" else "V"
            var_mut = (child["VAR"][idx] != before)

        # Pattern mutation
        if rng.random() < MUT_PAT:
            child.setdefault("PAT", ["N","N"])
            idx = rng.randrange(2)
            before = child["PAT"][idx]
            child["PAT"][idx] = "s" if before == "N" else "N"
            pat_mut = (child["PAT"][idx] != before)

        if color_mut or var_mut or pat_mut:
            mut_any += 1

        # Track whether mutation changed expressed color (dominance)
        a0, b0 = base_child.get("CLR", ["G","G"])
        a1, b1 = child.get("CLR", ["G","G"])
        base_code = _dominant_color_code(a0, b0)
        new_code  = _dominant_color_code(a1, b1)
        if new_code != base_code:
            mut_color_changed += 1

        if var_mut:
            mut_var_changed += 1
        if pat_mut:
            mut_pat_changed += 1

        # Phenotype tallies from the potentially mutated child
        a, b = child.get("CLR", ["G","G"])
        dom = _dominant_color_code(a, b)
        color_counts.update([dom])

        hs = 0
        for L in ("H1","H2","H3","H4"):
            aa = child.get(L, ["h","h"])
            hs += (1 if aa[0]=="H+" else 0) + (1 if aa[1]=="H+" else 0)
        h_sum += min(8, hs)

        var = child.get("VAR", ["V","V"])
        if var[0] == "v" and var[1] == "v":
            vv_count += 1

        homo = 0; total = 0
        for L, aa in child.items():
            if isinstance(aa, list) and len(aa)==2:
                total += 1
                if aa[0] == aa[1]:
                    homo += 1
        stability_sum += (homo / max(1, total))

    if color_counts:
        top_code, top_cnt = color_counts.most_common(1)[0]
        top_color = CODE_TO_NAME.get(top_code, "green")
        p_top = top_cnt / trials
    else:
        top_color, p_top = "green", 1.0

    p_non_green = 1.0 - (color_counts.get("G", 0) / trials)

    return {
        # legacy / existing fields
        "p_colored": p_non_green,
        "p_variegated": vv_count / trials,
        "h_mean": h_sum / trials,
        "stability": stability_sum / trials,
        "top_color": top_color,
        "p_top_color": p_top,
        # new explicit mutation diagnostics (all deterministic)
        "p_any_mutation": mut_any / trials,
        "p_color_changed_by_mut": mut_color_changed / trials,
        "p_var_locus_mutated": mut_var_changed / trials,
        "p_pat_locus_mutated": mut_pat_changed / trials,
    }

