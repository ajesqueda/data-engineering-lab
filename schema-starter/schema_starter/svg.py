"""A standalone SVG ER diagram: no Mermaid, opens in any browser, embeds anywhere.

Tables are laid out in columns by how far down the chain of links they are: tables
that point at nothing come first, then the tables that point at them, and so on.
Each link is a curve from the parent to the child's link column, with crow's-foot
ends: a bar for "one", a circle for "can be none", three prongs for "many".

With animate=True the cards rise in column by column and the links draw themselves
(CSS inside the SVG, so it also plays where scripts can't run, like a GitHub README).
Viewers who ask for reduced motion get the finished picture.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from .erd import _type
from .model import Table

CARD_W, HEAD_H, ROW_H, PAD = 290, 40, 26, 12
GAP_X, GAP_Y, MARGIN = 120, 36, 32
ACCENTS = ["#0071e3", "#8e44ef", "#00a5a8", "#ff7a1a", "#e8336d"]

SANS = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace"
STYLE = "\n".join([
    "  .bg { fill: #fbfbfd; }",
    "  .card { fill: #ffffff; stroke: #d2d2d7; stroke-width: 1; }",
    f"  .name {{ font: 600 15px {SANS}; fill: #1d1d1f; }}",
    f"  .col {{ font: 400 13px {SANS}; fill: #1d1d1f; }}",
    f"  .type {{ font: 400 12px {MONO}; fill: #86868b; }}",
    f"  .key {{ font: 600 9.5px {SANS}; letter-spacing: .04em; }}",
    "  .pk { fill: #0071e3; } .fk { fill: #8e44ef; } .uk { fill: #00a5a8; }",
    "  .rule { stroke: #f0f0f2; stroke-width: 1; }",
    "  .link { fill: none; stroke: #86868b; stroke-width: 1.4; }",
    "  .end { fill: none; stroke: #86868b; stroke-width: 1.4; }",
    "  .ring { fill: #fbfbfd; stroke: #86868b; stroke-width: 1.4; }",
    "",
])
MOTION = "\n".join([
    "  @keyframes rise { from { opacity: 0; transform: translateY(14px); }",
    "                    to { opacity: 1; transform: none; } }",
    "  @keyframes draw { from { stroke-dashoffset: 1; } to { stroke-dashoffset: 0; } }",
    "  @keyframes appear { from { opacity: 0; } to { opacity: 1; } }",
    "  .table { opacity: 0; animation: rise .7s cubic-bezier(.2,.8,.2,1) forwards; }",
    "  .link { stroke-dasharray: 1; stroke-dashoffset: 1; animation: draw .9s ease-out forwards; }",
    "  .ends { opacity: 0; animation: appear .3s ease-out forwards; }",
    "  @media (prefers-reduced-motion: reduce) {",
    "    .table, .ends { animation: none; opacity: 1; }",
    "    .link { animation: none; stroke-dasharray: none; stroke-dashoffset: 0; }",
    "  }",
    "",
])


def layers(tables: list[Table]) -> dict[str, int]:
    """0 for tables that point at nothing, else one more than their deepest parent."""
    by = {t.name: t for t in tables}
    depth: dict[str, int] = {}

    def visit(name: str, seen: frozenset[str]) -> int:
        if name in depth:
            return depth[name]
        parents = [fk.references for fk in by[name].foreign_keys
                   if fk.references != name and fk.references in by
                   and fk.references not in seen]
        d = 1 + max((visit(p, seen | {name}) for p in parents), default=-1)
        depth[name] = d
        return d

    for t in tables:
        visit(t.name, frozenset())
    return depth


def _height(t: Table) -> int:
    return HEAD_H + len(t.columns) * ROW_H + PAD // 2


def render(tables: list[Table], title: str | None = None, animate: bool = True) -> str:
    depth = layers(tables)
    columns: dict[int, list[Table]] = {}
    for t in sorted(tables, key=lambda t: t.name):
        columns.setdefault(depth[t.name], []).append(t)
    # Within a column, put children near their parents: sort by the parents' rows.
    row_of: dict[str, float] = {}
    for d in sorted(columns):
        if d:
            columns[d].sort(key=lambda t: (
                sum(row_of.get(fk.references, 0) for fk in t.foreign_keys)
                / max(len(t.foreign_keys), 1), t.name))
        for i, t in enumerate(columns[d]):
            row_of[t.name] = i

    top = MARGIN + (62 if title else 24)
    pos: dict[str, tuple[int, int]] = {}
    for d, col in columns.items():
        y = top
        for t in col:
            pos[t.name] = (MARGIN + d * (CARD_W + GAP_X), y)
            y += _height(t) + GAP_Y
    width = MARGIN * 2 + (max(columns) + 1) * CARD_W + max(columns) * GAP_X
    height = max(y for y in (pos[t.name][1] + _height(t) for t in tables)) + MARGIN

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
           f'width="{width}" height="{height}" role="img" '
           f'aria-label="{escape(title or "Entity relationship diagram", {chr(34): "&quot;"})}">',
           "<defs>",
           '<filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">'
           '<feDropShadow dx="0" dy="4" stdDeviation="8" flood-color="#000" '
           'flood-opacity="0.07"/></filter>',
           "</defs>",
           f"<style>{STYLE}{MOTION if animate else ''}</style>",
           f'<rect class="bg" width="{width}" height="{height}" rx="18"/>']
    if title:
        out.append(f'<text class="name" x="{MARGIN}" y="{MARGIN + 18}" '
                   f'style="font-size:20px">{escape(title)}</text>')
    legend_y = MARGIN + (40 if title else 4)
    out.append(f'<text class="type" x="{MARGIN}" y="{legend_y}">'
               f'<tspan class="key pk">PK</tspan> key   <tspan class="key fk">FK</tspan> link   '
               f'<tspan class="key uk">UK</tspan> unique   ? can be empty   '
               f'|| one   o one or none   &lt; many</text>')

    # Where each link leaves its parent: spread down the parent's right edge, in the
    # order of the children's rows, so the marks don't sit on top of each other.
    leaving: dict[str, list[tuple[float, str, str]]] = {}
    for t in tables:
        for fk in t.foreign_keys:
            if fk.references in {x.name for x in tables} and fk.references != t.name:
                child_y = pos[t.name][1] + HEAD_H + [c.name for c in t.columns].index(
                    fk.column) * ROW_H
                leaving.setdefault(fk.references, []).append((child_y, t.name, fk.column))
    start_y: dict[tuple[str, str], float] = {}
    for parent, outs in leaving.items():
        outs.sort()
        px_top = pos[parent][1] + HEAD_H
        room = _height(next(x for x in tables if x.name == parent)) - HEAD_H - 16
        step = min(18, room / max(len(outs), 1))
        for i, (_, child, column) in enumerate(outs):
            start_y[(child, column)] = px_top + ROW_H / 2 + i * step

    by = {t.name: t for t in tables}
    links, ends = [], []
    n_links = 0
    for t in sorted(tables, key=lambda t: t.name):
        cx, cy = pos[t.name]
        col_index = {c.name: i for i, c in enumerate(t.columns)}
        for fk in t.foreign_keys:
            if fk.references not in by:
                continue
            col = t.column(fk.column)
            px, py = pos[fk.references]
            y2 = cy + HEAD_H + col_index[fk.column] * ROW_H + ROW_H / 2
            y1 = start_y.get((t.name, fk.column), py + HEAD_H / 2)
            delay = 0.35 + 0.25 * depth[t.name] + 0.06 * n_links
            n_links += 1
            if fk.references == t.name:  # a self link loops round the right side
                x = cx + CARD_W
                d = (f"M{x} {y1} C{x + 70} {y1} {x + 70} {y2} {x} {y2}")
                start, end, flip = (x, y1), (x, y2), -1
            else:
                x1, x2 = px + CARD_W, cx
                bend = max(60, (x2 - x1) / 2)
                d = f"M{x1} {y1} C{x1 + bend} {y1} {x2 - bend} {y2} {x2} {y2}"
                start, end, flip = (x1, y1), (x2, y2), 1
            style = f' style="animation-delay:{delay:.2f}s"' if animate else ""
            links.append(f'<path class="link" pathLength="1" d="{d}"{style}/>')
            ends.append(_ends(start, end, flip, col.not_null, col.unique,
                              f' style="animation-delay:{delay + 0.7:.2f}s"' if animate else ""))
    out += links + ends

    for t in tables:
        x, y = pos[t.name]
        accent = ACCENTS[depth[t.name] % len(ACCENTS)]
        style = f' style="animation-delay:{0.12 * depth[t.name] + 0.04 * row_of[t.name]:.2f}s"'
        out.append(f'<g class="table"{style if animate else ""}>')
        h = _height(t)
        out.append(f'<rect class="card" x="{x}" y="{y}" width="{CARD_W}" height="{h}" '
                   f'rx="14" filter="url(#shadow)"/>')
        out.append(f'<rect x="{x}" y="{y}" width="{CARD_W}" height="4" rx="2" '
                   f'fill="{accent}"/>')
        out.append(f'<text class="name" x="{x + 16}" y="{y + 26}">{escape(t.name)}</text>')
        fk_cols = {fk.column for fk in t.foreign_keys}
        for i, c in enumerate(t.columns):
            ry = y + HEAD_H + i * ROW_H
            out.append(f'<line class="rule" x1="{x + 12}" y1="{ry}" x2="{x + CARD_W - 12}" '
                       f'y2="{ry}"/>')
            keys = [k for k, on in (("PK", c.name in t.primary_key), ("FK", c.name in fk_cols),
                                    ("UK", c.unique)) if on]
            kx = x + 16
            for k in keys:
                out.append(f'<text class="key {k.lower()}" x="{kx}" y="{ry + 17}">{k}</text>')
                kx += 20
            label = escape(c.name) + ("" if c.not_null or c.name in t.primary_key else "?")
            out.append(f'<text class="col" x="{max(kx, x + 58)}" y="{ry + 17}">{label}</text>')
            out.append(f'<text class="type" x="{x + CARD_W - 16}" y="{ry + 17}" '
                       f'text-anchor="end">{escape(_type(c.type))}</text>')
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _ends(start, end, flip, not_null: bool, unique: bool, style: str) -> str:
    """Crow's-foot marks: at the parent, a bar (and a ring if the link can be NULL);
    at the child, three prongs for many or a bar for one."""
    (sx, sy), (ex, ey) = start, end
    parts = [f'<g class="ends"{style}>']
    m = 5 * flip
    parts.append(f'<line class="end" x1="{sx + 2 * m}" y1="{sy - 5}" x2="{sx + 2 * m}" '
                 f'y2="{sy + 5}"/>')
    if not_null:
        parts.append(f'<line class="end" x1="{sx + 3 * m}" y1="{sy - 5}" x2="{sx + 3 * m}" '
                     f'y2="{sy + 5}"/>')
    else:
        parts.append(f'<circle class="ring" cx="{sx + 4 * m}" cy="{sy}" r="3.5"/>')
    tip = ex - 14 * flip
    if unique:
        parts.append(f'<line class="end" x1="{tip}" y1="{ey - 7}" x2="{tip}" y2="{ey + 7}"/>')
    else:
        parts.append(f'<path class="end" d="M{tip} {ey} L{ex} {ey - 7} M{tip} {ey} L{ex} {ey} '
                     f'M{tip} {ey} L{ex} {ey + 7}"/>')
    parts.append(f'<circle class="ring" cx="{tip - 7 * flip}" cy="{ey}" r="4.5"/>')
    parts.append("</g>")
    return "".join(parts)
