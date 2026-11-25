"""Ask a few plain questions about a business and write down the answers as a spec.

The questions follow normalization instead of asking about tables:

- "What do you keep track of?"            each thing becomes its own table
- "What do you record about each one?"    facts that depend on that thing alone
- "Can it have more than one?"            a list gets its own table (1NF)
- "Does it belong to one ...?"            a link, instead of copying the parent's facts
- "Which things pair up many-to-many?"    a pair table whose key is both links (2NF)

`ask` and `say` are passed in, so tests can script the answers.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .spec import RESERVED, TYPE_HELP, TYPES, SpecError, check, name_problem, suggest

Ask = Callable[[str], str]
Say = Callable[[str], None]

ATTRIBUTE_FORMAT = """\
One per line: name type [required] [unique] [many]
  types: {types}
  choice:a|b|c lists the allowed values, rating:1-10 sets the range
  many = it can have more than one (phone numbers, tags)
  e.g.  email email required unique
        status choice:draft|paid|shipped required
Leave a line empty when you're done."""

DELETE_RULES = {"b": "restrict", "block": "restrict", "d": "cascade", "delete": "cascade",
                "k": "set null", "keep": "set null"}


def parse_attribute(line: str) -> dict:
    """'status choice:draft|paid required' -> an attribute dict (ValueError if it can't)."""
    words = line.split()
    if len(words) < 2:
        raise ValueError("give a name and a type, like 'price money required'")
    name, kind, *flags = words
    if p := name_problem(name, "the name"):
        raise ValueError(p)
    attr: dict = {"name": name}
    base, _, arg = kind.partition(":")
    if base not in TYPES:
        raise ValueError(f"unknown type {base!r}; types are {', '.join(sorted(TYPES))}")
    attr["type"] = base
    if base == "choice":
        choices = [c for c in arg.split("|") if c]
        if not choices:
            raise ValueError("a choice lists its values: choice:small|medium|large")
        attr["choices"] = choices
    elif base in ("rating", "integer") and arg:
        m = re.fullmatch(r"(-?\d+)-(-?\d+)", arg)
        if not m or int(m.group(1)) >= int(m.group(2)):
            raise ValueError(f"write the range as {base}:1-10 (low-high)")
        attr["min"], attr["max"] = int(m.group(1)), int(m.group(2))
    elif arg:
        raise ValueError(f"{base} doesn't take ':{arg}'")
    for flag in flags:
        if flag not in ("required", "unique", "many"):
            raise ValueError(f"unknown word {flag!r}: use required, unique or many")
        attr[flag] = True
    return attr


def _names(answer: str) -> list[str]:
    return [a.strip() for a in answer.split(",") if a.strip()]


def _yes(ask: Ask, question: str, default: bool) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        answer = ask(f"{question} {hint} ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "n", "no"):
            return answer.startswith("y")


def _attributes(ask: Ask, say: Say, prompt: str, allow_many: bool) -> list[dict]:
    attrs: list[dict] = []
    say(prompt)
    while line := ask("  > ").strip():
        try:
            attr = parse_attribute(line)
            if attr.get("many") and not allow_many:
                raise ValueError("a pair's facts can't be 'many'")
            if any(a["name"] == attr["name"] for a in attrs):
                raise ValueError(f"{attr['name']!r} is already listed")
        except ValueError as exc:
            say(f"  ! {exc}")
            continue
        attrs.append(attr)
    return attrs


def _entity_names(ask: Ask, say: Say) -> list[str]:
    while True:
        raw = _names(ask("What things does the business keep track of? Singular and "
                         "comma-separated, e.g. customer, product, appointment\n> "))
        if not raw:
            say("  ! name at least one thing")
            continue
        names = [suggest(n) for n in raw]
        for typed, used in zip(raw, names, strict=True):
            if typed != used:
                say(f"  '{typed}' will be called '{used}'"
                    + (" (it's a reserved word in SQL)" if typed.lower() in RESERVED else ""))
        if len(set(names)) != len(names):
            say("  ! a thing is listed twice")
            continue
        return names


def interview(ask: Ask | None = None, say: Say | None = None) -> dict:
    ask = ask or input  # looked up now, so a test can replace builtins.input
    say = say or print
    say("schema-starter: a few questions, then a normalized PostgreSQL schema.\n")
    business = suggest(ask("What's the business called? (one word or two)\n> ") or "business")
    say(f"  schema name: {business}\n")
    names = _entity_names(ask, say)
    fmt = ATTRIBUTE_FORMAT.format(types=", ".join(sorted(TYPE_HELP)))
    say("")

    entities = []
    for i, name in enumerate(names):
        description = ask(f"In a few words, what is a {name}? (optional)\n> ").strip()
        # The full format once; after that a one-line reminder.
        how = fmt if i == 0 else ("Same format: name type [required] [unique] [many]. "
                                  "Empty line when done.")
        attrs = _attributes(ask, say, f"What do you record about each {name}? Each "
                            f"{name} gets an id and a created_at time automatically.\n{how}",
                            allow_many=True)
        ent: dict = {"name": name, "attributes": attrs}
        if description:
            ent["description"] = description
        entities.append(ent)
        say("")

    relationships: list[dict] = []
    for name in names:
        others = [n for n in names if n != name]
        if not others:
            break
        answer = ask(f"Does each {name} belong to one of these? {', '.join(others)}\n"
                     f"(comma-separated, or leave empty)\n> ")
        for parent in _names(answer):
            parent = suggest(parent)
            if parent not in others:
                say(f"  ! {parent!r} isn't one of: {', '.join(others)} (skipped)")
                continue
            required = _yes(ask, f"  Must every {name} have a {parent}?", True)
            while True:
                rule = ask(f"  If a {parent} is deleted, what happens to its {name}s? "
                           f"[b]lock the delete / [d]elete them too"
                           + ("" if required else " / [k]eep them, unlinked") + " ").strip()
                rule = DELETE_RULES.get(rule.lower() or "b")
                if rule and not (required and rule == "set null"):
                    break
                say("  ! choose one of the letters in brackets")
            relationships.append({"type": "belongs_to", "child": name, "parent": parent,
                                  "required": required, "on_delete": rule})
        say("")

    if len(names) > 1:
        answer = ask("Which things pair up many-to-many? (a student takes many classes AND "
                     "a class has many students)\nWrite pairs like student-class, "
                     "comma-separated, or leave empty\n> ")
        for pair in _names(answer):
            a, _, b = (suggest(x) for x in pair.partition("-"))
            if a not in names or b not in names or a == b:
                say(f"  ! {pair!r} isn't two different things from the list (skipped)")
                continue
            attrs = _attributes(ask, say, f"What do you record about each {a}-{b} pair? "
                                "(e.g. quantity count required)\nLeave a line empty when "
                                "you're done, or right away for nothing.", allow_many=False)
            rel: dict = {"type": "many_to_many", "between": [a, b]}
            if attrs:
                rel["attributes"] = attrs
            relationships.append(rel)

    spec = {"name": business, "entities": entities, "relationships": relationships}
    try:
        check(spec)
    except SpecError as exc:
        say("\nThe answers have a few problems; fix them in the spec file and run again:")
        say(str(exc))
    return spec
