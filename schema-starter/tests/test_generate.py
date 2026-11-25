"""DDL and diagram from a spec, without a database."""

import copy
import json
from pathlib import Path

from schema_starter import ddl, erd, model
from schema_starter.spec import check

EXAMPLE = json.loads((Path(__file__).parents[1] / "examples" / "bakery.json").read_text())


def tables(s=EXAMPLE):
    check(s)
    return {t.name: t for t in model.build(s)}


def test_every_table_comes_after_the_tables_it_points_at():
    order = [t.name for t in model.build(EXAMPLE)]
    for t in model.build(EXAMPLE):
        for fk in t.foreign_keys:
            if fk.references != t.name:
                assert order.index(fk.references) < order.index(t.name)


def test_lists_and_pairs_get_their_own_tables():
    t = tables()
    phone = t["customer_phone"]
    assert phone.primary_key == ["customer_id", "phone"]
    assert phone.foreign_keys[0].on_delete == "cascade"
    line = t["order_line"]
    assert line.primary_key == ["customer_order_id", "product_id"]
    assert [fk.on_delete for fk in line.foreign_keys] == ["cascade", "restrict"]
    assert "phone" not in {c.name for c in t["customer"].columns}


def test_types_and_checks():
    product = tables()["product"]
    assert product.column("price").type == "numeric(12,2)"
    assert product.column("price").check == "price >= 0"
    assert product.column("category").check == "category IN ('bread', 'pastry', 'cake')"
    assert tables()["customer_order"].column("pickup_at").type == "timestamp with time zone"
    email = tables()["customer"].column("email")
    assert "email = lower(email)" in email.check and email.unique and email.not_null


def test_every_link_gets_an_index_unless_one_already_starts_with_it():
    t = tables()
    assert t["customer_order"].fk_indexes() == ["customer_id"]
    assert t["order_line"].fk_indexes() == ["product_id"]  # customer_order_id leads the PK
    assert t["customer_phone"].fk_indexes() == []
    assert t["review"].fk_indexes() == ["customer_id"]  # product_id leads the UNIQUE pair


def test_script_is_one_transaction_and_quotes_text():
    sql = ddl.render(model.build(EXAMPLE), "bakery", description=EXAMPLE["description"])
    assert sql.startswith("-- bakery") and "\nBEGIN;\n" in sql and sql.endswith("COMMIT;\n")
    assert sql.index("CREATE SCHEMA bakery;") < sql.index("SET LOCAL search_path TO bakery;")
    assert "'A customer''s rating" in sql
    assert "UNIQUE (product_id, customer_id)" in sql
    assert "DROP SCHEMA" not in sql
    assert "DROP SCHEMA IF EXISTS bakery CASCADE;" in ddl.render(model.build(EXAMPLE), "bakery",
                                                                 replace=True)


def test_optional_links_in_a_loop_are_added_after_both_tables_exist():
    s = {"name": "org", "entities": [{"name": "team"}, {"name": "person"}],
         "relationships": [
             {"type": "belongs_to", "child": "team", "parent": "person", "as": "lead"},
             {"type": "belongs_to", "child": "person", "parent": "team", "required": True}]}
    check(s)
    sql = ddl.render(model.build(s), "org")
    assert "ALTER TABLE team ADD FOREIGN KEY (lead_id) REFERENCES person" in sql
    assert sql.index("CREATE TABLE person") < sql.index("ALTER TABLE team")


def test_self_link_stays_inline():
    s = {"name": "org", "entities": [{"name": "employee"}], "relationships": [
        {"type": "belongs_to", "child": "employee", "parent": "employee", "as": "manager",
         "on_delete": "set null"}]}
    sql = ddl.render(model.build(s), "org")
    assert "bigint REFERENCES employee (employee_id) ON DELETE SET NULL" in " ".join(sql.split())
    assert "ALTER TABLE" not in sql


def test_diagram_cardinality():
    text = erd.mermaid(model.build(EXAMPLE))
    assert 'customer ||--o{ customer_order : "customer_id"' in text  # required
    assert 'customer |o--o{ review : "customer_id"' in text  # optional
    assert "bigint customer_order_id PK, FK" in text
    assert 'numeric price "numeric(12,2), NOT NULL"' in text
    assert "text email UK" in text


def test_one_to_one_link_is_drawn_as_at_most_one():
    s = copy.deepcopy(EXAMPLE)
    s["entities"].append({"name": "loyalty_card", "attributes": [{"name": "points",
                                                                   "type": "count"}]})
    s["relationships"].append({"type": "belongs_to", "child": "loyalty_card",
                               "parent": "customer", "required": True, "unique": True})
    check(s)
    assert 'customer ||--o| loyalty_card : "customer_id"' in erd.mermaid(model.build(s))


def test_markdown_wraps_the_diagram_for_github():
    md = erd.markdown(model.build(EXAMPLE), "bakery")
    assert md.startswith("# bakery\n") and "```mermaid\nerDiagram\n" in md


def test_committed_examples_are_up_to_date():
    """examples/bakery.sql and bakery-erd.md must match what the tool makes now.

    Regenerate with: python -m schema_starter sql examples/bakery.json > examples/bakery.sql
    and a deploy with --erd examples/bakery-erd.md.
    """
    from schema_starter.__main__ import script
    here = Path(__file__).parents[1] / "examples"
    assert (here / "bakery.sql").read_text() == script(EXAMPLE, "bakery.json", False)
    assert erd.mermaid(model.build(EXAMPLE)).rstrip() in (here / "bakery-erd.md").read_text()
    readme = (here.parent / "README.md").read_text()
    assert erd.mermaid(model.build(EXAMPLE)).rstrip() in readme, "README diagram is stale"
