# Pixel-art plant & seed sprites with louder stage differences.
# Genome: supports simple keys (c, vv, h, leaves) or loci (CLR, VAR, H1..H4, ML)

import html

# ---------- Genome helpers ----------
COLOR_MAP = {
    "green":  ("#6ac85a", "#3a8f39"),
    "red":    ("#ef6b68", "#b9423f"),
    "yellow": ("#f6da69", "#d4b64a"),
    "purple": ("#b491ff", "#7c62cf"),
    "teal":   ("#66d1c1", "#3ca495"),
    "white":  ("#eef3ff", "#bfc8e6"),
}
DOM_ORDER = {"R": 5, "P": 4, "G": 3, "Y": 2, "T": 1}
CLR_TO_NAME = {"R": "red", "P": "purple", "G": "green", "Y": "yellow", "T": "teal"}

def _dominant_color_from_clr(alleles):
    if not isinstance(alleles, (list, tuple)) or not alleles:
        return "green"
    a = alleles[0]; b = alleles[1] if len(alleles) > 1 else a
    code = a if DOM_ORDER.get(a, 3) >= DOM_ORDER.get(b, 3) else b
    return CLR_TO_NAME.get(code, "green")

def _resolve_color_name(genome):
    c = (genome or {}).get("c")
    if isinstance(c, str) and c in COLOR_MAP:
        return c
    clr = (genome or {}).get("CLR")
    if clr:
        return _dominant_color_from_clr(clr)
    return "green"

def _variegated(genome):
    if "vv" in (genome or {}):
        v = genome.get("vv")
        return bool(v) and str(v).lower() not in ("0", "false", "none", "")
    VAR = (genome or {}).get("VAR")
    if isinstance(VAR, (list, tuple)) and len(VAR) >= 2:
        return VAR[0] == "v" and VAR[1] == "v"
    return False

def _height_score(genome):
    if "h" in (genome or {}):
        try: return max(0, min(8, int(genome.get("h", 4))))
        except: return 4
    score = 0
    for L in ("H1","H2","H3","H4"):
        a = (genome or {}).get(L, ["h","h"])
        if isinstance(a, (list, tuple)) and len(a) >= 2:
            score += (1 if a[0] == "H+" else 0) + (1 if a[1] == "H+" else 0)
    return max(0, min(8, score))

def _leafiness(genome, h):
    if "leaves" in (genome or {}):
        try: return max(1, min(5, int(genome["leaves"])))
        except: pass
    ml = (genome or {}).get("ML")
    bonus = 0
    if isinstance(ml, (list, tuple)) and len(ml) >= 2:
        bonus = (1 if ml[0] == "L+" else 0) + (1 if ml[1] == "L+" else 0)
    base = 1 + (h // 2)   # 0..8 -> 1..5
    return max(1, min(5, base + bonus))

# ---------- Pixel canvas helpers ----------
def _px_canvas(w, h, px=6, margin=2, bg=None):
    return {"w": w, "h": h, "px": px, "m": margin, "bg": bg, "cells": []}

def _put(cv, x, y, color):
    if 0 <= x < cv["w"] and 0 <= y < cv["h"]:
        cv["cells"].append((x, y, color))

def _rect(cv, x, y, w, h, color):
    for yy in range(y, y+h):
        for xx in range(x, x+w):
            _put(cv, xx, yy, color)

def _svg_from_canvas(cv, width=100, height=90):
    px = cv["px"]; m = cv["m"]
    W = m*2 + cv["w"]*px
    H = m*2 + cv["h"]*px
    scale = min(width / W, height / H)
    panel = f'<rect x="1" y="1" width="{width-2}" height="{height-2}" rx="12" fill="#0f1422" stroke="#2a3147"/>'
    pot   = f'<rect x="{14}" y="{height-16}" width="{width-28}" height="10" rx="5" fill="#3a3f55"/>'
    soil  = f'<rect x="{18}" y="{height-20}" width="{width-36}" height="8" rx="4" fill="#3d2b1f" stroke="#2a1d13"/>'
    rects = []
    if cv["bg"]:
        rects.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="{cv["bg"]}"/>')
    for (x, y, color) in cv["cells"]:
        rx = m + x*px; ry = m + y*px
        rects.append(f'<rect x="{rx*scale:.3f}" y="{ry*scale:.3f}" width="{px*scale:.3f}" height="{px*scale:.3f}" fill="{color}"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">{panel}{soil}{pot}' + "".join(rects) + '</svg>'

# ---------- Pixel shapes ----------
def _pix_stem(cv, x, y_bottom, height, color1="#2aa95a", color2="#208a49"):
    for yy in range(y_bottom-height, y_bottom):
        _rect(cv, x-1, yy, 1, 1, color1)
        _rect(cv, x,   yy, 1, 1, color2)

def _pix_leaf_pair(cv, x_mid, y, spread, main, shade, varieg=False):
    _rect(cv, x_mid - spread - 3, y, 3, 1, main)
    _rect(cv, x_mid - spread - 4, y+1, 4, 1, main)
    _rect(cv, x_mid - spread - 3, y+2, 3, 1, shade)
    if varieg: _rect(cv, x_mid - spread - 2, y+1, 1, 1, "#ffffff")
    _rect(cv, x_mid + spread, y, 3, 1, main)
    _rect(cv, x_mid + spread, y+1, 4, 1, main)
    _rect(cv, x_mid + spread+1, y+2, 3, 1, shade)
    if varieg: _rect(cv, x_mid + spread+2, y+1, 1, 1, "#ffffff")

def _pix_bud_tiny(cv, x_mid, y, color):
    _rect(cv, x_mid, y, 1, 1, color)

def _pix_bud(cv, x_mid, y, color):
    _rect(cv, x_mid-1, y, 3, 1, color)
    _rect(cv, x_mid-2, y+1, 5, 1, color)

def _pix_prebloom(cv, x_mid, y, main, shade):
    # four small petals hint
    _rect(cv, x_mid-1, y-1, 1, 1, main)
    _rect(cv, x_mid+1, y-1, 1, 1, main)
    _rect(cv, x_mid-1, y+1, 1, 1, shade)
    _rect(cv, x_mid+1, y+1, 1, 1, shade)
    _rect(cv, x_mid,   y,   1, 1, "#ffe47a")

def _pix_flower(cv, x_mid, y_mid, pet_main, pet_shade, center="#ffe47a", varieg=False):
    _rect(cv, x_mid-2, y_mid-3, 5, 1, pet_main)
    _rect(cv, x_mid-3, y_mid-2, 7, 1, pet_main)
    _rect(cv, x_mid-4, y_mid-1, 9, 1, pet_main)
    _rect(cv, x_mid-4, y_mid,   9, 1, pet_shade)
    _rect(cv, x_mid-3, y_mid+1, 7, 1, pet_shade)
    _rect(cv, x_mid-2, y_mid+2, 5, 1, pet_shade)
    _rect(cv, x_mid-1, y_mid-1, 3, 3, center)
    if varieg:
        _rect(cv, x_mid-3, y_mid-1, 1, 3, "#ffffff")
        _rect(cv, x_mid+3, y_mid-1, 1, 3, "#ffffff")
        _rect(cv, x_mid-1, y_mid-3, 3, 1, "#ffffff")
        _rect(cv, x_mid-1, y_mid+3, 3, 1, "#ffffff")

# ---------- Seeds ----------
def render_seed_svg(species: str) -> str:
    cv = _px_canvas(16, 12, px=6, margin=2)
    _rect(cv, 7, 5, 2, 2, "#6b5238")
    _rect(cv, 6, 5, 1, 2, "#543e2b")
    _rect(cv, 9, 5, 1, 2, "#543e2b")
    _rect(cv, 7, 5, 1, 1, "#8b6a49")
    svg = _svg_from_canvas(cv, width=100, height=90)
    label = html.escape(species or "seed")
    return svg.replace("</svg>", f'<text x="50" y="20" fill="#9aa0ae" font-size="10" text-anchor="middle">{label}</text></svg>')

# ---------- Plant ----------
def render_plant_svg(genome: dict, stage: str, pid: str) -> str:
    color_name = _resolve_color_name(genome)
    pet_main, pet_shade = COLOR_MAP.get(color_name, COLOR_MAP["green"])
    varieg = _variegated(genome)
    h = _height_score(genome)        # 0..8
    tiers = _leafiness(genome, h)    # 1..5

    cv = _px_canvas(16, 12, px=6, margin=2)
    xmid = 8
    soil_y = 10

    stem_pix = 3 + int(round(h * 0.9))        # 3..10
    crown_y  = soil_y - stem_pix - 1

    st = (stage or "seedling").lower()

    # stem
    _pix_stem(cv, xmid, soil_y, stem_pix)

    # leaves
    max_tiers = {
        "seedling": 1,
        "juvenile": max(1, min(2, tiers)),
        "mature":   max(2, min(3, tiers)),
        "flowering":min(5, tiers),
        "spent":    max(2, min(3, tiers)),
    }.get(st, max(1, min(2, tiers)))
    spread = 3 + (1 if h >= 4 else 0) + (1 if h >= 7 else 0)
    for i in range(max_tiers):
        y = soil_y - 2 - i*2
        _pix_leaf_pair(cv, xmid, y, spread, "#6ccf5c", "#419a3f", varieg and (i % 2 == 0))
        if tiers >= 4 and i % 2 == 0:
            _rect(cv, xmid - spread - 5, y+1, 1, 1, "#6ccf5c")
        if tiers >= 5 and i % 2 == 1:
            _rect(cv, xmid + spread + 5, y+1, 1, 1, "#6ccf5c")

    # stage head (LOUD differences)
    if st == "seedling":
        _pix_bud_tiny(cv, xmid, crown_y+1, pet_main)
    elif st == "juvenile":
        _pix_bud(cv, xmid, crown_y, pet_main)
    elif st == "mature":
        _pix_prebloom(cv, xmid, crown_y-1, pet_main, pet_shade)
    elif st == "flowering":
        _pix_flower(cv, xmid, crown_y-1, pet_main, pet_shade, center="#ffe47a", varieg=varieg)
    elif st == "spent":
        _pix_flower(cv, xmid, crown_y, pet_main, pet_shade, center="#cdbb6a", varieg=False)
        cv["cells"] = [(x,y, "#9ba0a8" if c in (pet_main, pet_shade) else c) for (x,y,c) in cv["cells"]]

    return _svg_from_canvas(cv, width=100, height=90)
