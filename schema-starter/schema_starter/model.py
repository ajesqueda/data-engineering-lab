"""Tables, columns and keys: one model that the DDL and the ER diagram both come from.

`build(spec)` turns a checked spec into tables. `db.introspect` builds the same model
from a live database's catalog, so the diagram of what was deployed can be compared
with the diagram of what was asked for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Each spec type: PostgreSQL's own name for the column type (as format_type() prints it),
# and the CHECK it gets. {c} is the column name.
TYPE_SQL = {
    "text": "text",
    "integer": "integer",
    "count": "integer",
    "decimal": "numeric",
    "money": "numeric(12,2)",
    "boolean": "boolean",
    "date": "date",
    "moment": "timestamp with time zone",
    "email": "text",
    "choice": "text",
    "rating": "smallint",
}
EMAIL_PATTERN = r"^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$"


@dataclass
class Column:
    name: str
    type: str
    not_null: bool = False
    unique: bool = False
    check: str | None = None
    default: str | None = None
    identity: bool = False
    comment: str | None = None


@dataclass
class ForeignKey:
    column: str
    references: str
    on_delete: str = "restrict"


@dataclass
class Table:
    name: str
    columns: list[Column]
    primary_key: list[str]
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    comment: str | None = None
    unique_together: list[list[str]] = field(default_factory=list)

    def column(self, name: str) -> Column:
        return next(c for c in self.columns if c.name == name)

    def fk_indexes(self) -> list[str]:
        """FK columns that need their own index (PostgreSQL doesn't add one).

        An FK that is the first column of the primary key, or unique by itself, is
        already the start of an index, so it's skipped.
        """
        covered = {self.primary_key[0]} | {c.name for c in self.columns if c.unique}
        covered |= {group[0] for group in self.unique_together}
        return [fk.column for fk in self.foreign_keys if fk.column not in covered]


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def check_for(attr: dict, column: str) -> str | None:
    kind = attr["type"]
    if kind == "text" and (attr.get("required") or attr.get("many")):
        return f"{column} <> ''"
    if kind == "count":
        return f"{column} >= 0"
    if kind == "money":
        return f"{column} >= 0"
    if kind == "email":
        return f"{column} = lower({column}) AND {column} ~ {literal(EMAIL_PATTERN)}"
    if kind == "choice":
        return f"{column} IN ({', '.join(literal(c) for c in attr['choices'])})"
    if kind == "rating":
        return f"{column} BETWEEN {attr.get('min', 1)} AND {attr.get('max', 5)}"
    if kind == "integer":
        lo, hi = attr.get("min"), attr.get("max")
        if lo is not None and hi is not None:
            return f"{column} BETWEEN {lo} AND {hi}"
        if lo is not None:
            return f"{column} >= {lo}"
        if hi is not None:
            return f"{column} <= {hi}"
    return None


def attribute_column(attr: dict, not_null: bool | None = None, unique: bool | None = None
                     ) -> Column:
    return Column(
        name=attr["name"],
        type=TYPE_SQL[attr["type"]],
        not_null=bool(attr.get("required")) if not_null is None else not_null,
        unique=bool(attr.get("unique")) if unique is None else unique,
        check=check_for(attr, attr["name"]),
        comment=attr.get("description"),
    )


def build(spec: dict) -> list[Table]:
    """Tables in creation order: every table comes after the tables it points at."""
    tables: dict[str, Table] = {}
    after: dict[str, set[str]] = {}  # table -> tables that must exist first

    for ent in spec["entities"]:
        name = ent["name"]
        cols = [Column(f"{name}_id", "bigint", not_null=True, identity=True)]
        cols += [attribute_column(a) for a in ent.get("attributes", []) if not a.get("many")]
        tables[name] = Table(name, cols, [f"{name}_id"], comment=ent.get("description"))
        after[name] = set()

    for rel in spec.get("relationships", []):
        if rel["type"] != "belongs_to":
            continue
        child, parent = tables[rel["child"]], rel["parent"]
        column = f"{rel.get('as', parent)}_id"
        child.columns.append(Column(column, "bigint", not_null=bool(rel.get("required")),
                                    unique=bool(rel.get("unique"))))
        child.foreign_keys.append(ForeignKey(column, parent, rel.get("on_delete", "restrict")))
        if parent != child.name:
            after[child.name].add(parent)

    # Combinations that can't repeat; a link is named by its parent (or 'as').
    for ent in spec["entities"]:
        table = tables[ent["name"]]
        columns = {c.name for c in table.columns}
        for group in ent.get("unique_together", []):
            table.unique_together.append(
                [g if g in columns else f"{g}_id" for g in group])

    if spec.get("created_at", True):
        for ent in spec["entities"]:
            tables[ent["name"]].columns.append(
                Column("created_at", "timestamp with time zone", not_null=True,
                       default="now()"))

    # A list attribute ("many": true) gets its own table: one row per value (1NF).
    for ent in spec["entities"]:
        owner = ent["name"]
        for attr in ent.get("attributes", []):
            if not attr.get("many"):
                continue
            name = f"{owner}_{attr['name']}"
            cols = [Column(f"{owner}_id", "bigint", not_null=True),
                    attribute_column(attr, not_null=True)]
            tables[name] = Table(name, cols, [f"{owner}_id", attr["name"]],
                                 [ForeignKey(f"{owner}_id", owner, "cascade")],
                                 comment=f"Each {attr['name']} of a {owner}, one per row.")
            after[name] = {owner}

    # Many-to-many: a pair table whose key is both links (and facts about the pair).
    for rel in spec.get("relationships", []):
        if rel["type"] != "many_to_many":
            continue
        a, b = rel["between"]
        rule_a, rule_b = rel.get("on_delete", ["cascade", "restrict"])
        name = rel.get("name", f"{a}_{b}")
        cols = [Column(f"{a}_id", "bigint", not_null=True),
                Column(f"{b}_id", "bigint", not_null=True)]
        cols += [attribute_column(x) for x in rel.get("attributes", [])]
        tables[name] = Table(name, cols, [f"{a}_id", f"{b}_id"],
                             [ForeignKey(f"{a}_id", a, rule_a), ForeignKey(f"{b}_id", b, rule_b)],
                             comment=rel.get("description"))
        after[name] = {a, b}

    return _ordered(tables, after)


def _ordered(tables: dict[str, Table], after: dict[str, set[str]]) -> list[Table]:
    """Spec order, except a table waits until everything it points at exists.

    Optional links may form a loop (spec.check rejects loops of required ones); such
    a link points at a table created later, so ddl adds it afterwards with ALTER TABLE.
    """
    done: list[str] = []
    waiting = list(tables)
    while waiting:
        ready = [t for t in waiting if after[t] <= set(done)]
        pick = ready[0] if ready else waiting[0]  # a loop: break it at the first table
        done.append(pick)
        waiting.remove(pick)
    return [tables[t] for t in done]
