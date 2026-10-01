"""Parse chemical formulas and compute molar mass and mass composition."""
import json
import re
from collections import OrderedDict
from pathlib import Path

ELEMENTS = {
    sym: {"name": v[0], "mass": v[1]}
    for sym, v in json.loads((Path(__file__).parent.parent / "data" / "elements.json").read_text()).items()
}

TOKEN = re.compile(r"([A-Z][a-z]?|\(|\)|\d+)")


def _parse_group(formula: str) -> "OrderedDict[str, int]":
    """Parse a formula without hydrate dots, e.g. 'Al2(SO4)3'."""
    stack = [OrderedDict()]
    tokens = TOKEN.findall(formula)
    if "".join(tokens) != formula:
        raise ValueError(f"Unrecognised characters in formula: {formula}")
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "(":
            stack.append(OrderedDict())
        elif tok == ")":
            group = stack.pop()
            mult = 1
            if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                mult = int(tokens[i + 1])
                i += 1
            for el, n in group.items():
                stack[-1][el] = stack[-1].get(el, 0) + n * mult
        elif tok.isdigit():
            raise ValueError(f"Unexpected number in {formula}")
        else:
            if tok not in ELEMENTS:
                raise ValueError(f"Unknown element '{tok}' in {formula}")
            n = 1
            if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                n = int(tokens[i + 1])
                i += 1
            stack[-1][tok] = stack[-1].get(tok, 0) + n
        i += 1
    if len(stack) != 1:
        raise ValueError(f"Unbalanced parentheses in {formula}")
    return stack[0]


def parse(formula: str) -> "OrderedDict[str, int]":
    """Parse a full formula, including hydrates written with '·' (e.g. CuSO4·5H2O)."""
    total = OrderedDict()
    for part in formula.split("·"):
        m = re.match(r"^(\d+)(.*)$", part)
        mult, body = (int(m.group(1)), m.group(2)) if m else (1, part)
        for el, n in _parse_group(body).items():
            total[el] = total.get(el, 0) + n * mult
    return total


def analyse(formula: str) -> dict:
    """Return molar mass and a per-element breakdown for a formula."""
    counts = parse(formula)
    rows = []
    for sym, n in counts.items():
        mass = ELEMENTS[sym]["mass"]
        rows.append({"symbol": sym, "name": ELEMENTS[sym]["name"], "count": n,
                     "atomic_mass": mass, "subtotal": n * mass})
    molar_mass = sum(r["subtotal"] for r in rows)
    for r in rows:
        r["percent"] = 100 * r["subtotal"] / molar_mass
    return {"molar_mass": molar_mass, "rows": rows, "atoms": sum(counts.values())}


def pretty(formula: str) -> str:
    """HTML version of a formula with subscripts: H2SO4 -> H<sub>2</sub>SO<sub>4</sub>."""
    out = []
    for part_i, part in enumerate(formula.split("·")):
        m = re.match(r"^(\d+)(.*)$", part)
        prefix, body = (m.group(1), m.group(2)) if m else ("", part)
        if part_i:
            out.append("·")
        out.append(prefix + re.sub(r"(?<=[A-Za-z\)])(\d+)", r"<sub>\1</sub>", body))
    return "".join(out)
