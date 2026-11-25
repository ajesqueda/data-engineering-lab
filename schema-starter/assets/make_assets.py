"""Regenerate the README and landing-page graphics from the tool's real output.

    python assets/make_assets.py        (from schema-starter/)

- hero.svg      the banner
- terminal.svg  a real `init` session (scripted answers), typing itself out
- erd.svg       the bakery example drawn by `erd --svg`
- docs copies   the landing page in ../docs/schema-starter/ gets the same files

The animations are CSS inside the SVGs, so they also play in a GitHub README, where
scripts can't run.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
sys.path.insert(0, str(TOOL))

from schema_starter import model, svg  # noqa: E402
from schema_starter.interview import interview  # noqa: E402

SITE = TOOL.parent / "docs" / "schema-starter"
FONT = "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace"

ANSWERS = ["Corner Bakery", "customer, product, Order", "Someone who orders from us",
           "full_name text required", "email email required unique", "phone text many", "",
           "", "title text required unique", "price money required",
           "stock_count count required", "",
           "", "pickup_at moment required", "status choice:placed|ready|picked_up required", "",
           "", "", "customer", "", "b",
           "order-product", "quantity count required", "unit_price money required", ""]

# Which lines of the real session to show, so the window stays short.
KEEP = ["What's the business called?", "What things does the business keep track of?",
        "'Order' will be called", "What do you record about each customer?",
        "Does each customer_order belong", "If a customer is deleted",
        "Which things pair up many-to-many?", "What do you record about each customer_order-"]


def shorten(prompt: str) -> str:
    """The first question of a prompt, without the hints in brackets."""
    text = prompt.strip()
    if "?" in text and not text.startswith("Does each"):
        text = text[: text.index("?") + 1]
    return text.split(" (")[0].split(" [b]lock")[0].removesuffix(":")


def session() -> tuple[list[tuple[str, str, str]], dict]:
    """Run the real interview with scripted answers.

    Returns (indent, text, answer) rows for the kept questions, and the spec it made.
    A kept question shows its answer on the next line; attribute lines ("  > ...")
    belong to the most recent "What do you record about each ..." header.
    """
    rows: list[tuple[str, str, str]] = []
    answers = iter(ANSWERS)
    header = ""

    def kept(text: str) -> bool:
        return any(text.strip().startswith(k) for k in KEEP)

    def say(text: str) -> None:
        nonlocal header
        for line in text.split("\n"):
            if line.startswith("What do you record about each"):
                header = line
            if kept(line):
                rows.append((" " * (len(line) - len(line.lstrip())), shorten(line), ""))

    def ask(prompt: str) -> str:
        answer = next(answers)
        *before, last = prompt.split("\n")
        for line in before:
            say(line)
        if last.startswith("  >"):  # an attribute line, under the current header
            if answer and kept(header):
                rows.append(("  ", "›", answer))
        elif last.startswith(">"):  # the question was on the lines before
            if before and kept(before[0]) and answer:
                rows.append(("", "›", answer))
        elif kept(last):  # a one-line question, answered on the same line
            rows.append((" " * (len(last) - len(last.lstrip())), shorten(last), answer or "b"))
        return answer

    spec = interview(ask, say)
    return rows, spec


def terminal(rows: list[tuple[str, str, str]], tables: int, name: str) -> str:
    lines = [("cmd", "", "python -m schema_starter init", "")]
    lines += [("row", indent, prompt, answer) for indent, prompt, answer in rows]
    lines += [("note", "", f"wrote {name}.json", ""),
              ("cmd", "", f"python -m schema_starter deploy {name}.json --db shop", ""),
              ("note", "", f"created schema {name} with {tables} tables; "
                           f"diagram in {name}-erd.md", "")]
    w, line_h, top = 860, 22, 62
    h = top + len(lines) * line_h + 22
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
           f'height="{h}" role="img" aria-label="A schema-starter session in a terminal">',
           "<style>",
           f"  text {{ font: 13.5px {MONO}; white-space: pre; fill: #a1a1a6; }}",
           "  .l { opacity: 0; animation: show .01s linear forwards; }",
           "  .a { fill: #64d2ff; } .p { fill: #bf5af2; } .c { fill: #f5f5f7; }",
           "  .ok { fill: #30d158; }",
           "  @keyframes show { to { opacity: 1; } }",
           "  @media (prefers-reduced-motion: reduce) { .l { animation: none; opacity: 1; } }",
           "</style>",
           f'<rect width="{w}" height="{h}" rx="14" fill="#1d1d1f"/>',
           f'<path d="M0 14 a14 14 0 0 1 14 -14 h{w - 28} a14 14 0 0 1 14 14 v24 h-{w} z" '
           'fill="#2c2c2e"/>',
           '<circle cx="22" cy="19" r="6.5" fill="#ff5f57"/>',
           '<circle cx="44" cy="19" r="6.5" fill="#febc2e"/>',
           '<circle cx="66" cy="19" r="6.5" fill="#28c840"/>',
           f'<text x="{w / 2}" y="23" text-anchor="middle" '
           f'style="font: 12.5px {FONT}; fill: #8e8e93">schema-starter — zsh</text>']
    t = 0.3
    for i, (kind, indent, text, answer) in enumerate(lines):
        y = top + i * line_h
        if kind == "cmd":
            body = f'<tspan class="p">$ </tspan><tspan class="c">{escape(text)}</tspan>'
            t += 1.0
        elif kind == "note":
            body = f'<tspan class="ok">{escape(text)}</tspan>'
            t += 0.5
        elif text == "›":
            body = f'{indent}<tspan class="p">› </tspan><tspan class="a">{escape(answer)}</tspan>'
            t += 0.5
        else:
            body = f"{indent}{escape(text)}"
            if answer:
                body += f' <tspan class="a">{escape(answer)}</tspan>'
                if answer == "b":
                    body += " (block the delete)"
            t += 0.35
        out.append(f'<text class="l" x="24" y="{y}" style="animation-delay:{t:.2f}s">'
                   f"{body}</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _line(y: int, text: str, fill: str, size: int, delay: float = 0, weight: int = 400,
          spacing: str = "0") -> str:
    style = (f"font-size:{size}px;font-weight:{weight};letter-spacing:{spacing};"
             f"animation-delay:{delay}s")
    return (f'<text class="t up" x="600" y="{y}" text-anchor="middle" fill="{fill}" '
            f'style="{style}">{escape(text)}</text>')


def hero() -> str:
    w, h = 1200, 420
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" role="img" aria-label="schema-starter: describe your business, '
        'get a database">',
        "<defs>",
        '<linearGradient id="g" x1="0" x2="1" y1="0" y2="0">'
        '<stop offset="0" stop-color="#2997ff"/><stop offset=".5" stop-color="#bf5af2"/>'
        '<stop offset="1" stop-color="#ff6482"/></linearGradient>',
        '<radialGradient id="glow" cx=".5" cy=".9" r=".7">'
        '<stop offset="0" stop-color="#2997ff" stop-opacity=".28"/>'
        '<stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>',
        "</defs>",
        "<style>",
        f"  .t {{ font-family: {FONT}; }}",
        "  .up { opacity: 0; animation: up 1s cubic-bezier(.2,.8,.2,1) forwards; }",
        "  @keyframes up { from { opacity: 0; transform: translateY(18px); }",
        "                  to { opacity: 1; transform: none; } }",
        "  @keyframes breathe { 50% { opacity: .55; } }",
        "  .glow { animation: breathe 6s ease-in-out infinite; }",
        "  @media (prefers-reduced-motion: reduce) {",
        "    .up { animation: none; opacity: 1; } .glow { animation: none; } }",
        "</style>",
        f'<rect width="{w}" height="{h}" rx="24" fill="#000"/>',
        f'<rect class="glow" width="{w}" height="{h}" rx="24" fill="url(#glow)"/>',
        _line(92, "schema-starter", "#86868b", 20, 0, 600, ".02em"),
        _line(190, "Describe your business.", "#f5f5f7", 64, .15, 700, "-.02em"),
        _line(268, "Get a database.", "url(#g)", 64, .35, 700, "-.02em"),
        _line(336, "Plain questions in. A normalized, constrained PostgreSQL schema out,",
              "#a1a1a6", 22, .6),
        _line(366, "deployed in one transaction, with a diagram of what was built.",
              "#a1a1a6", 22, .6),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def main() -> None:
    rows, spec = session()
    tables = len(model.build(spec))
    bakery = json.loads((TOOL / "examples" / "bakery.json").read_text())
    files = {
        "hero.svg": hero(),
        "terminal.svg": terminal(rows, tables, spec["name"]),
        "erd.svg": svg.render(model.build(bakery), "bakery: data model"),
    }
    SITE.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (HERE / name).write_text(text)
        print(f"wrote assets/{name}")
    shutil.copy(HERE / "erd.svg", SITE / "erd.svg")
    shutil.copy(HERE / "terminal.svg", SITE / "terminal.svg")
    print(f"copied erd.svg and terminal.svg to {SITE.relative_to(TOOL.parent)}/")


if __name__ == "__main__":
    main()
