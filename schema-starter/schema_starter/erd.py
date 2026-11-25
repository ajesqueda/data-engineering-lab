"""A Mermaid ER diagram of the model. GitHub draws Mermaid blocks in Markdown files.

Each link is drawn from the table it points at to the table that holds the link:

    customer ||--o{ customer_order : "customer_id"

||  every order has exactly one customer (the link column is NOT NULL)
|o  an order may have no customer (the link column can be NULL)
o{  a customer has zero or more orders
o|  a customer has at most one (the link column is UNIQUE: one-to-one)
"""

from __future__ import annotations

import re

from .model import Table

SHORT = {"timestamp with time zone": "timestamptz", "timestamp without time zone": "timestamp",
         "character varying": "varchar"}


def _type(sql_type: str) -> str:
    base = re.sub(r"\(.*\)", "", sql_type).strip()
    return SHORT.get(base, base).replace(" ", "_")


def mermaid(tables: list[Table]) -> str:
    lines = ["erDiagram"]
    by_name = sorted(tables, key=lambda t: t.name)
    links = []
    for table in by_name:
        cols = {c.name: c for c in table.columns}
        for fk in table.foreign_keys:
            col = cols[fk.column]
            parent_side = "||" if col.not_null else "|o"
            child_side = "o|" if col.unique else "o{"
            links.append((fk.references, table.name, fk.column,
                          f'    {fk.references} {parent_side}--{child_side} {table.name} : '
                          f'"{fk.column}"'))
    lines += [line for *_, line in sorted(links)]
    for table in by_name:
        fk_cols = {fk.column for fk in table.foreign_keys}
        lines.append(f"    {table.name} {{")
        for col in table.columns:
            keys = [k for k, on in (("PK", col.name in table.primary_key),
                                    ("FK", col.name in fk_cols),
                                    ("UK", col.unique)) if on]
            notes = []
            if "(" in col.type:  # numeric(12,2): Mermaid types can't hold the precision
                notes.append(col.type)
            if col.not_null and col.name not in table.primary_key:
                notes.append("NOT NULL")
            line = f"        {_type(col.type)} {col.name}"
            if keys:
                line += " " + ", ".join(keys)
            if notes:
                line += ' "' + ", ".join(notes) + '"'
            lines.append(line)
        lines.append("    }")
    return "\n".join(lines) + "\n"


def markdown(tables: list[Table], title: str, note: str = "") -> str:
    """A Markdown file with the diagram, ready to commit or open on GitHub."""
    parts = [f"# {title}", ""]
    if note:
        parts += [note, ""]
    parts += ["```mermaid", mermaid(tables).rstrip(), "```", ""]
    return "\n".join(parts)
