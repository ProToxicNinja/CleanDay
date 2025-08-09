import json, uuid, random
from pathlib import Path
from app.db import get_conn, exec1, q

TRAITS_PATH = Path("app/genetics/traits.json")
TRAITS = json.loads(TRAITS_PATH.read_text())

SPECIES = ["Pea", "Tomato", "Marigold"]

def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"

def get_or_create_player() -> str:
    pid = uuid.uuid4().hex
    conn = get_conn()
    exec1(conn, "INSERT OR REPLACE INTO users(id, name) VALUES(?, ?)", (pid, f"Player-{pid[:4]}"))
    rows = q(conn, "SELECT COUNT(*) AS c FROM seeds WHERE user_id=?", (pid,))
    if rows[0]["c"] == 0:
        grant_starter_pack(conn, pid)
    conn.close()
    return pid

def _wchoice(pairs):
    # pairs: list[(value, weight)], weights needn't sum to 1
    total = sum(w for _, w in pairs)
    r = random.random() * total
    acc = 0.0
    for v, w in pairs:
        acc += w
        if r <= acc:
            return v
    return pairs[-1][0]

def random_genome():
    genome = {}
    for trait in TRAITS["traits"]:
        t = trait["type"]
        if t == "mendelian":
            locus = trait["loci"][0]
            dom, rec = trait["dominance"]
            p_dom = trait["alleles"][dom]["p"]
            p_rec = trait["alleles"][rec]["p"]
            a1 = _wchoice([(dom, p_dom), (rec, p_rec)])
            a2 = _wchoice([(dom, p_dom), (rec, p_rec)])
            genome[locus] = [a1, a2]

        elif t == "polygenic":
            p_plus = trait["alleles"]["H+"]["p"]
            p_min  = trait["alleles"]["h"]["p"]
            for locus in trait["loci"]:
                a1 = _wchoice([("H+", p_plus), ("h", p_min)])
                a2 = _wchoice([("H+", p_plus), ("h", p_min)])
                genome[locus] = [a1, a2]

        elif t == "epistatic":
            locus = trait["loci"][0]
            p_on  = trait["alleles"]["V"]["p"]
            p_off = trait["alleles"]["v"]["p"]
            a1 = _wchoice([("V", p_on), ("v", p_off)])
            a2 = _wchoice([("V", p_on), ("v", p_off)])
            genome[locus] = [a1, a2]
    return genome

def grant_starter_pack(conn, user_id: str):
    for sp in SPECIES:
        genome = random_genome()
        lot_id = uid("seed")
        exec1(conn,
              "INSERT INTO seeds(id,user_id,species,genome_json,qty,generation,parents_json) VALUES(?,?,?,?,?,?,?)",
              (lot_id, user_id, sp, json.dumps(genome), 10, "F1", json.dumps({"mom": None, "dad": None})))

def express_phenotype(genome: dict):
    color = "white"
    variegation = False
    height_score = 0

    for trait in TRAITS["traits"]:
        ttype = trait["type"]
        if ttype == "mendelian" and trait["id"] == "petal_color":
            locus = trait["loci"][0]
            dom, rec = trait["dominance"]
            alleles = genome.get(locus, [rec, rec])
            color = "colored" if dom in alleles else "white"

        if ttype == "epistatic" and trait["id"] == "variegation":
            locus = trait["loci"][0]
            a_on = trait["alleles"]["V"]["code"]
            alleles = genome.get(locus, [a_on, a_on])
            variegation = (alleles[0] == "v" and alleles[1] == "v")

        if ttype == "polygenic" and trait["id"] == "height":
            total = 0
            for locus in trait["loci"]:
                a = genome.get(locus, ["h","h"])
                total += (1 if a[0] == "H+" else 0) + (1 if a[1] == "H+" else 0)
            height_score = total

    appearance = "variegated " + color if variegation else color
    return { "appearance": appearance, "height_score": height_score }

def next_generation_label(gen: str | None) -> str:
    try:
        if not gen or not gen.upper().startswith("F"):
            return "F1"
        n = int(gen[1:])
        return f"F{n+1}"
    except:
        return "F1"