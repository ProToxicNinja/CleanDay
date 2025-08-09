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

def random_genome():
    genome = {}
    for trait in TRAITS["traits"]:
        t = trait["type"]
        if t == "mendelian":
            locus = trait["loci"][0]
            dom, rec = trait["dominance"]
            a1 = random.choice([dom, rec])
            a2 = random.choice([dom, rec])
            genome[locus] = [a1, a2]
        elif t == "polygenic":
            for locus in trait["loci"]:
                aplus = trait["alleles"]["H+"]["code"]
                aminus = trait["alleles"]["h"]["code"]
                genome[locus] = [random.choice([aplus, aminus]), random.choice([aplus, aminus])]
        elif t == "epistatic":
            locus = trait["loci"][0]
            a_on = trait["alleles"]["V"]["code"]
            a_off = trait["alleles"]["v"]["code"]
            genome[locus] = [random.choice([a_on, a_off]), random.choice([a_on, a_off])]
    return genome

def grant_starter_pack(conn, user_id: str):
    for sp in SPECIES:
        genome = random_genome()
        lot_id = uid("seed")
        exec1(conn,
              "INSERT INTO seeds(id,user_id,species,genome_json,qty,generation) VALUES(?,?,?,?,?,?)",
              (lot_id, user_id, sp, json.dumps(genome), 10, "F1"))

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
