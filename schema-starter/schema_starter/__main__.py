"""schema-starter: describe a business, get a normalized PostgreSQL schema.

    python -m schema_starter init                      ask the questions, write <name>.json
    python -m schema_starter check bakery.json         list every problem in a spec
    python -m schema_starter sql bakery.json           print the DDL
    python -m schema_starter deploy bakery.json --db bakery_dev
                                                       create it (one transaction), then
                                                       draw the tables that now exist
    python -m schema_starter erd bakery.json           draw the diagram from the spec
    python -m schema_starter erd bakery.json --svg -o bakery.svg
                                                       ... as a standalone animated SVG
    python -m schema_starter erd --db bakery_dev --schema bakery
                                                       draw any live schema
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db, ddl, erd, interview, model, spec, svg


def _load(path: str) -> dict:
    try:
        return spec.load(path)
    except FileNotFoundError:
        raise SystemExit(f"error: no such file: {path}") from None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: {path} isn't valid JSON: {exc}") from None
    except spec.SpecError as exc:
        raise SystemExit(f"error: {path} has problems:\n{exc}") from None


def script(s: dict, path: str, replace: bool) -> str:
    return ddl.render(model.build(s), s["name"], replace, Path(path).name, s.get("description"))


def cmd_init(args) -> int:
    answers = interview.interview()
    out = Path(args.output or f"{answers['name']}.json")
    if out.exists() and not args.force:
        print(f"error: {out} exists; use --output or --force", file=sys.stderr)
        return 1
    out.write_text(json.dumps(answers, indent=2) + "\n")
    print(f"\nwrote {out}. Next:\n  python -m schema_starter sql {out}\n"
          f"  python -m schema_starter deploy {out} --db <database>")
    try:
        spec.check(answers)
    except spec.SpecError:
        return 1
    return 0


def cmd_check(args) -> int:
    s = _load(args.spec)
    tables = model.build(s)
    print(f"{args.spec}: OK, {len(tables)} tables: {', '.join(t.name for t in tables)}")
    return 0


def cmd_sql(args) -> int:
    s = _load(args.spec)
    print(script(s, args.spec, args.replace), end="")
    return 0


def cmd_deploy(args) -> int:
    s = _load(args.spec)
    schema = s["name"]
    try:
        if db.schema_exists(args.db, schema) and not args.replace:
            print(f"error: schema {schema!r} already exists in that database. Use --replace "
                  f"to drop it and everything in it, then create it again.", file=sys.stderr)
            return 1
    except db.DatabaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        db.deploy(args.db, script(s, args.spec, args.replace))
    except db.DatabaseError as exc:
        print(f"error: nothing was changed (the whole script is one transaction, and it "
              f"was rolled back):\n{exc}", file=sys.stderr)
        return 1
    try:
        live = db.introspect(args.db, schema)
    except db.DatabaseError as exc:
        print(f"created schema {schema}, but couldn't read it back to draw it:\n{exc}",
              file=sys.stderr)
        return 1
    out = Path(args.erd or f"{schema}-erd.md")
    if out.suffix == ".svg":
        out.write_text(svg.render(live, f"{schema}: data model"))
    else:
        out.write_text(erd.markdown(live, f"{schema}: data model",
                                    f"Read from the live database after `deploy` "
                                    f"({len(live)} tables in schema `{schema}`)."))
    print(f"created schema {schema} with {len(live)} tables; diagram in {out}")
    return 0


def cmd_erd(args) -> int:
    if args.db:
        schema = args.schema or (args.spec and _load(args.spec)["name"])
        if not schema:
            print("error: with --db, give --schema (or a spec)", file=sys.stderr)
            return 1
        try:
            tables = db.introspect(args.db, schema)
        except db.DatabaseError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if not tables:
            print(f"error: schema {schema!r} has no tables in that database", file=sys.stderr)
            return 1
        title = f"{schema}: data model (live)"
    elif args.spec:
        s = _load(args.spec)
        tables, title = model.build(s), f"{s['name']}: data model"
    else:
        print("error: give a spec, or --db and --schema", file=sys.stderr)
        return 1
    as_svg = args.svg or (args.output or "").endswith(".svg")
    text = svg.render(tables, title, animate=not args.still) if as_svg else erd.markdown(
        tables, title)
    if args.output:
        Path(args.output).write_text(text)
        print(f"wrote {args.output}")
    else:
        print(text, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="schema_starter", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="answer questions, write a spec")
    p.add_argument("-o", "--output")
    p.add_argument("--force", action="store_true", help="overwrite an existing spec")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("check", help="list every problem in a spec")
    p.add_argument("spec")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("sql", help="print the DDL")
    p.add_argument("spec")
    p.add_argument("--replace", action="store_true", help="start with DROP SCHEMA ... CASCADE")
    p.set_defaults(func=cmd_sql)

    p = sub.add_parser("deploy", help="create the schema, then draw what was created")
    p.add_argument("spec")
    p.add_argument("--db", required=True, help="anything psql -d accepts")
    p.add_argument("--replace", action="store_true",
                   help="drop the schema (and all its data) first")
    p.add_argument("--erd", help="where to write the diagram (default <schema>-erd.md; "
                   "a .svg name draws an SVG)")
    p.set_defaults(func=cmd_deploy)

    p = sub.add_parser("erd", help="draw the ER diagram (Mermaid in Markdown)")
    p.add_argument("spec", nargs="?")
    p.add_argument("--db", help="draw a live schema instead")
    p.add_argument("--schema")
    p.add_argument("-o", "--output", help="a .svg name implies --svg")
    p.add_argument("--svg", action="store_true", help="standalone SVG instead of Mermaid")
    p.add_argument("--still", action="store_true", help="SVG without the animation")
    p.set_defaults(func=cmd_erd)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
