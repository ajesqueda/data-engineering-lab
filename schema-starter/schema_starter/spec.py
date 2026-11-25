"""The business description (a JSON spec) and the checks that keep it in 3NF.

A spec lists the things a business keeps track of (entities), what it records about
each one (attributes), and how they connect (relationships). `check(spec)` collects
every problem at once, so a typo and a normalization mistake show up together:

- names that PostgreSQL can't use bare (`order`, `user`, `Order Items`)
- unknown keys and types, so `"requird": true` doesn't silently do nothing
- a repeating group like phone1, phone2 (1NF): mark the attribute `"many": true`
- a parent's fact copied onto a child, like customer_email on an order (3NF): the
  order already points at its customer, so the email belongs only there
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TYPES = {"text", "integer", "count", "decimal", "money", "boolean", "date", "moment",
         "email", "choice", "rating"}
TYPE_HELP = {
    "text": "words (required text can't be empty)",
    "integer": "a whole number, optional min/max",
    "count": "a whole number >= 0 (stock, quantity)",
    "decimal": "an exact number with a fraction (weights, rates)",
    "money": "an amount of money: exact, never negative",
    "boolean": "yes or no",
    "date": "a calendar day (a birthday, a due date)",
    "moment": "a real moment in time, stored with its time zone",
    "email": "an email address, stored in lower case",
    "choice": "one of a fixed list of values",
    "rating": "a score between min and max (default 1 to 5)",
}
ON_DELETE = {"restrict", "cascade", "set null"}

# PostgreSQL's reserved key words: a table or column can't use these without quotes.
RESERVED = set("""
all analyse analyze and any array as asc asymmetric authorization binary both case cast
check collate collation column concurrently constraint create cross current_catalog
current_date current_role current_schema current_time current_timestamp current_user
default deferrable desc distinct do else end except false fetch for foreign freeze from
full grant group having ilike in initially inner intersect into is isnull join lateral
leading left like limit localtime localtimestamp natural not notnull null offset on only
or order outer overlaps placing primary references returning right select session_user
similar some symmetric system_user table tablesample then to trailing true union unique
user using variadic verbose when where window with
""".split())
NAME = re.compile(r"[a-z][a-z0-9_]*")
MAX_IDENTIFIER = 63  # PostgreSQL silently cuts longer names, so two could collide

ENTITY_KEYS = {"name", "description", "attributes", "unique_together"}
ATTRIBUTE_KEYS = {"name", "type", "required", "unique", "many", "choices", "min", "max",
                  "description"}
BELONGS_KEYS = {"type", "child", "parent", "required", "on_delete", "as", "unique"}
MANY_KEYS = {"type", "between", "name", "on_delete", "attributes", "description"}
SPEC_KEYS = {"name", "description", "entities", "relationships", "created_at"}


class SpecError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(f"- {p}" for p in problems))


def load(path: str | Path) -> dict:
    spec = json.loads(Path(path).read_text())
    check(spec)
    return spec


def suggest(name: str) -> str:
    """A usable spelling for a name the user typed: 'Order Items' -> 'order_item'."""
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if s and s[0].isdigit():
        s = "n_" + s
    if s in RESERVED:
        s = {"order": "customer_order", "user": "app_user", "group": "user_group",
             "table": "dining_table"}.get(s, s + "_item")
    return s


def name_problem(name: object, what: str) -> str | None:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        hint = f" (try {suggest(name)!r})" if isinstance(name, str) and suggest(name) else ""
        return f"{what} {name!r} must be lower_snake_case, starting with a letter{hint}"
    if name in RESERVED:
        return f"{what} {name!r} is a reserved word in SQL (try {suggest(name)!r})"
    if len(name) > MAX_IDENTIFIER:
        return f"{what} {name!r} is longer than {MAX_IDENTIFIER} characters"
    return None


def _keys(obj: dict, allowed: set[str], what: str, problems: list[str]) -> None:
    for key in sorted(set(obj) - allowed):
        problems.append(f"{what}: unknown key {key!r} (allowed: {', '.join(sorted(allowed))})")


def _bool(obj: dict, key: str, what: str, problems: list[str]) -> None:
    if key in obj and not isinstance(obj[key], bool):
        problems.append(f"{what}: {key!r} must be true or false")


def _attribute(attr: object, where: str, problems: list[str], allow_many: bool = True) -> None:
    if not isinstance(attr, dict):
        problems.append(f"{where}: each attribute is an object with a name and a type")
        return
    what = f"{where}.{attr.get('name', '?')}"
    _keys(attr, ATTRIBUTE_KEYS, what, problems)
    if p := name_problem(attr.get("name"), "attribute"):
        problems.append(f"{where}: {p}")
    kind = attr.get("type")
    if kind not in TYPES:
        problems.append(f"{what}: unknown type {kind!r} (types: {', '.join(sorted(TYPES))})")
    for key in ("required", "unique", "many"):
        _bool(attr, key, what, problems)
    if attr.get("many") and not allow_many:
        problems.append(f"{what}: a pair's attribute can't be 'many'")
    if attr.get("many") and kind == "boolean":
        problems.append(f"{what}: a list of yes/no values has no meaning; use a choice")
    choices = attr.get("choices")
    if kind == "choice":
        if (not isinstance(choices, list) or not choices
                or not all(isinstance(c, str) and c for c in choices)):
            problems.append(f"{what}: a choice needs 'choices', a list of non-empty strings")
        elif len(set(choices)) != len(choices):
            problems.append(f"{what}: 'choices' lists a value twice")
    elif choices is not None:
        problems.append(f"{what}: 'choices' only applies to the choice type")
    lo, hi = attr.get("min"), attr.get("max")
    if kind in ("integer", "rating"):
        for key, val in (("min", lo), ("max", hi)):
            if val is not None and (isinstance(val, bool) or not isinstance(val, int)):
                problems.append(f"{what}: {key!r} must be a whole number")
        if isinstance(lo, int) and isinstance(hi, int) and lo >= hi:
            problems.append(f"{what}: 'min' must be smaller than 'max'")
    elif lo is not None or hi is not None:
        problems.append(f"{what}: 'min'/'max' only apply to integer and rating")


def _repeating_groups(entity: str, attrs: list[dict], problems: list[str]) -> None:
    """book1, book2, book3 in one table is a repeating group (not in 1NF)."""
    stems: dict[str, list[str]] = {}
    for a in attrs:
        if m := re.fullmatch(r"([a-z_]*?)_?(\d+)(_[a-z0-9_]+)?", str(a.get("name", ""))):
            stems.setdefault(m.group(1) + (m.group(3) or ""), []).append(a["name"])
    for stem, names in stems.items():
        if len(names) > 1:
            problems.append(
                f"{entity}: {', '.join(names)} is a repeating group (not in 1NF): record "
                f"one {stem!r} attribute with \"many\": true, or make it its own entity")


def check(spec: object) -> None:
    """Raise SpecError listing every problem, or return None if the spec is usable."""
    problems: list[str] = []
    if not isinstance(spec, dict):
        raise SpecError(["the spec is a JSON object with name, entities and relationships"])
    _keys(spec, SPEC_KEYS, "spec", problems)
    if p := name_problem(spec.get("name"), "business name"):
        problems.append(p)
    _bool(spec, "created_at", "spec", problems)

    entities = spec.get("entities")
    if not isinstance(entities, list) or not entities:
        problems.append("spec: 'entities' must list at least one thing to keep track of")
        entities = []
    attrs_of: dict[str, dict[str, dict]] = {}
    for ent in entities:
        if not isinstance(ent, dict):
            problems.append("each entity is an object with a name and attributes")
            continue
        name = ent.get("name")
        _keys(ent, ENTITY_KEYS, f"entity {name!r}", problems)
        bad_name = name_problem(name, "entity")
        if bad_name:
            problems.append(bad_name)
        elif name in attrs_of:
            problems.append(f"entity {name!r} is listed twice")
            continue
        attrs = ent.get("attributes", [])
        if not isinstance(attrs, list):
            problems.append(f"{name}: 'attributes' must be a list")
            attrs = []
        seen: dict[str, dict] = {}
        for attr in attrs:
            _attribute(attr, name, problems)
            if isinstance(attr, dict) and isinstance(attr.get("name"), str):
                if attr["name"] in seen:
                    problems.append(f"{name}: attribute {attr['name']!r} is listed twice")
                if attr["name"] == f"{name}_id":
                    problems.append(f"{name}: {name}_id is the id column, added automatically")
                seen[attr["name"]] = attr
        _repeating_groups(name, [a for a in attrs if isinstance(a, dict)], problems)
        if not bad_name:  # links to a badly named entity would only repeat its problem
            attrs_of[name] = seen

    rels = spec.get("relationships", [])
    if not isinstance(rels, list):
        problems.append("spec: 'relationships' must be a list")
        rels = []
    parents_of: dict[str, list[tuple[str, str]]] = {e: [] for e in attrs_of}  # (parent, link)
    fk_columns: dict[str, set[str]] = {e: set() for e in attrs_of}
    pairs: set[frozenset[str]] = set()
    for rel in rels:
        if not isinstance(rel, dict):
            problems.append("each relationship is an object with a type")
            continue
        kind = rel.get("type")
        if kind == "belongs_to":
            _belongs_to(rel, attrs_of, parents_of, fk_columns, problems)
        elif kind == "many_to_many":
            _many_to_many(rel, attrs_of, parents_of, pairs, problems)
        else:
            problems.append(f"relationship type {kind!r} must be 'belongs_to' or 'many_to_many'")

    _copied_facts(attrs_of, parents_of, problems)
    _unique_together(entities, attrs_of, fk_columns, problems)
    _cycles(rels, attrs_of, problems)
    if not problems:
        _table_names(spec, problems)
    if problems:
        raise SpecError(problems)


def _on_delete(value: object, what: str, problems: list[str]) -> None:
    if value not in ON_DELETE:
        problems.append(f"{what}: on_delete {value!r} must be one of {sorted(ON_DELETE)}")


def _belongs_to(rel, attrs_of, parents_of, fk_columns, problems) -> None:
    child, parent = rel.get("child"), rel.get("parent")
    what = f"{child} belongs_to {parent}"
    _keys(rel, BELONGS_KEYS, what, problems)
    for role, ent in (("child", child), ("parent", parent)):
        if ent not in attrs_of:
            problems.append(f"{what}: {role} {ent!r} isn't one of the entities")
    for key in ("required", "unique"):
        _bool(rel, key, what, problems)
    on_delete = rel.get("on_delete", "restrict")
    _on_delete(on_delete, what, problems)
    if on_delete == "set null" and rel.get("required"):
        problems.append(f"{what}: 'set null' can't keep a required link; use restrict or "
                        "cascade, or make the link optional")
    prefix = rel.get("as", parent)
    if "as" in rel and (p := name_problem(rel["as"], "'as'")):
        problems.append(f"{what}: {p}")
    if child not in attrs_of or parent not in attrs_of or not isinstance(prefix, str):
        return
    column = f"{prefix}_id"
    if column in fk_columns[child] or column in attrs_of[child] or column == f"{child}_id":
        problems.append(f"{what}: column {column!r} already exists on {child}; give this "
                        "link a different name with 'as' (e.g. 'manager')")
    fk_columns[child].add(column)
    if child != parent:
        parents_of[child].append((parent, prefix))


def _many_to_many(rel, attrs_of, parents_of, pairs, problems) -> None:
    between = rel.get("between")
    what = f"many_to_many {between}"
    _keys(rel, MANY_KEYS, what, problems)
    if (not isinstance(between, list) or len(between) != 2
            or not all(isinstance(e, str) for e in between)):
        problems.append(f"{what}: 'between' names exactly two entities")
        return
    a, b = between
    for ent in between:
        if ent not in attrs_of:
            problems.append(f"{what}: {ent!r} isn't one of the entities")
    if a == b:
        problems.append(f"{what}: an entity linked to itself needs two named links; use "
                        "an entity for the pair with two belongs_to links and 'as'")
        return
    if frozenset(between) in pairs:
        problems.append(f"{what}: this pair is linked twice")
    pairs.add(frozenset(between))
    if "name" in rel and (p := name_problem(rel["name"], "pair table")):
        problems.append(f"{what}: {p}")
    on_delete = rel.get("on_delete", ["cascade", "restrict"])
    if not isinstance(on_delete, list) or len(on_delete) != 2:
        problems.append(f"{what}: on_delete is a list of two rules, one per side")
    else:
        for rule in on_delete:
            _on_delete(rule, what, problems)
        if "set null" in on_delete:
            problems.append(f"{what}: a pair row can't exist without both sides, so "
                            "'set null' isn't allowed")
    attrs = rel.get("attributes", [])
    if not isinstance(attrs, list):
        problems.append(f"{what}: 'attributes' must be a list")
        return
    pair_name = rel.get("name", f"{a}_{b}")
    seen: dict[str, dict] = {}
    for attr in attrs:
        _attribute(attr, str(pair_name), problems, allow_many=False)
        if isinstance(attr, dict) and isinstance(attr.get("name"), str):
            if attr["name"] in (f"{a}_id", f"{b}_id") or attr["name"] in seen:
                problems.append(f"{pair_name}: attribute {attr['name']!r} is listed twice "
                                "or clashes with a link column")
            seen[attr["name"]] = attr
    if a in attrs_of and b in attrs_of:
        attrs_of[f"__pair__{pair_name}"] = seen
        parents_of[f"__pair__{pair_name}"] = [(a, a), (b, b)]


def _copied_facts(attrs_of, parents_of, problems) -> None:
    """customer_email on an order copies customer.email: a 3NF (transitive) problem."""
    for child, parents in parents_of.items():
        label = child.removeprefix("__pair__")
        for parent, link in parents:
            for attr in attrs_of.get(child, {}):
                fact = next((attr.removeprefix(f"{p}_") for p in (link, parent)
                             if attr.startswith(f"{p}_")), attr)
                if attr != fact and fact in attrs_of.get(parent, {}):
                    problems.append(
                        f"{label}.{attr} copies {parent}.{fact} (not in 3NF): {label} already "
                        f"links to its {parent}, so store {fact} once, on {parent}. If it's a "
                        f"different fact (like the price at the time of sale), give it a name "
                        f"that says so")


def _unique_together(entities, attrs_of, fk_columns, problems) -> None:
    """Combinations that must not repeat, like one review per customer per product."""
    for ent in entities:
        if not isinstance(ent, dict) or "unique_together" not in ent:
            continue
        name = ent.get("name")
        groups = ent["unique_together"]
        if not isinstance(groups, list) or not all(isinstance(g, list) for g in groups):
            problems.append(f"{name}: 'unique_together' is a list of lists of names")
            continue
        usable = {a for a, attr in attrs_of.get(name, {}).items() if not attr.get("many")}
        usable |= {c.removesuffix("_id") for c in fk_columns.get(name, set())}
        for group in groups:
            if len(group) < 2 or len(set(group)) != len(group):
                problems.append(f"{name}: unique_together {group} needs two or more "
                                "different names (one name alone: use \"unique\": true)")
            for item in group:
                if item not in usable:
                    problems.append(f"{name}: unique_together names {item!r}, which isn't one "
                                    f"of its attributes or links ({', '.join(sorted(usable))})")


def _cycles(rels, attrs_of, problems) -> None:
    """Required links that go round in a circle can never get their first row in."""
    graph: dict[str, set[str]] = {e: set() for e in attrs_of if not e.startswith("__")}
    for rel in rels:
        if (isinstance(rel, dict) and rel.get("type") == "belongs_to" and rel.get("required")
                and rel.get("child") in graph and rel.get("parent") in graph
                and rel.get("child") != rel.get("parent")):
            graph[rel["child"]].add(rel["parent"])
    state: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> None:
        state[node] = 1
        for nxt in sorted(graph[node]):
            if state.get(nxt) == 1:
                loop = path[path.index(nxt):] + [nxt]
                problems.append(f"required links go in a circle ({' -> '.join(loop)}), so no "
                                "row could ever be inserted first; make one of them optional")
            elif nxt not in state:
                visit(nxt, path + [nxt])
        state[node] = 2

    for node in sorted(graph):
        if node not in state:
            visit(node, [node])


def _table_names(spec: dict, problems: list[str]) -> None:
    """Entity, list and pair tables all share one namespace."""
    owner: dict[str, str] = {}

    def claim(table: str, why: str) -> None:
        if table in owner:
            problems.append(f"table {table!r} would be created twice ({owner[table]} and {why})")
        elif len(table) > MAX_IDENTIFIER:
            problems.append(f"table name {table!r} ({why}) is longer than {MAX_IDENTIFIER}")
        owner[table] = why

    for ent in spec["entities"]:
        claim(ent["name"], f"entity {ent['name']}")
    for ent in spec["entities"]:
        for attr in ent.get("attributes", []):
            if attr.get("many"):
                claim(f"{ent['name']}_{attr['name']}", f"the list of {ent['name']}.{attr['name']}")
    for rel in spec.get("relationships", []):
        if rel["type"] == "many_to_many":
            a, b = rel["between"]
            claim(rel.get("name", f"{a}_{b}"), f"the {a}-{b} pairs")
    if spec.get("created_at", True):
        for ent in spec["entities"]:
            if any(a["name"] == "created_at" for a in ent.get("attributes", [])):
                problems.append(f"{ent['name']}: 'created_at' is added automatically; remove "
                                "it, or set \"created_at\": false on the spec")
