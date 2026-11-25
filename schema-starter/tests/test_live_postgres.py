"""Deploy to a real PostgreSQL and check that the database itself enforces the rules.

Runs when SCHEMA_STARTER_TEST_DB names a database psql can reach (CI starts one);
skipped otherwise. Each test deploys into its own throwaway schema and drops it.
"""

import copy
import json
import os
import uuid
from pathlib import Path

import pytest
from schema_starter import __main__ as cli
from schema_starter import db, ddl, erd, model

DB = os.environ.get("SCHEMA_STARTER_TEST_DB")
pytestmark = pytest.mark.skipif(not DB, reason="set SCHEMA_STARTER_TEST_DB to run")
EXAMPLE_PATH = Path(__file__).parents[1] / "examples" / "bakery.json"
EXAMPLE = json.loads(EXAMPLE_PATH.read_text())


@pytest.fixture
def bakery(tmp_path):
    """The example deployed under a unique schema name; yields (spec path, schema)."""
    s = copy.deepcopy(EXAMPLE)
    s["name"] = f"t_{uuid.uuid4().hex[:12]}"
    path = tmp_path / "bakery.json"
    path.write_text(json.dumps(s))
    assert cli.main(["deploy", str(path), "--db", DB, "--erd", str(tmp_path / "erd.md")]) == 0
    yield path, s["name"]
    db.psql(DB, f"DROP SCHEMA IF EXISTS {s['name']} CASCADE;")


def sql(schema, statement):
    return db.psql(DB, f"SET search_path TO {schema};\n{statement}")


def rejects(schema, statement, error):
    with pytest.raises(db.DatabaseError, match=error):
        sql(schema, statement)


def seed(schema):
    sql(schema, """
        INSERT INTO customer (full_name, email) VALUES ('Ada', 'ada@example.com');
        INSERT INTO product (title, category, price, stock_count)
             VALUES ('Sourdough', 'bread', 6.50, 10);
        INSERT INTO customer_order (pickup_at, status, customer_id)
             VALUES ('2026-12-01 08:00-06', 'placed', 1);
        INSERT INTO order_line VALUES (1, 1, 2, 6.50);
        INSERT INTO review (rating, product_id, customer_id) VALUES (5, 1, 1);""")


def test_the_live_diagram_matches_the_spec(bakery, tmp_path):
    _, schema = bakery
    s = dict(EXAMPLE, name=schema)
    assert erd.mermaid(db.introspect(DB, schema)) == erd.mermaid(model.build(s))
    assert "erDiagram" in (tmp_path / "erd.md").read_text()


@pytest.mark.parametrize("statement, error", [
    ("INSERT INTO customer (full_name, email) VALUES ('Bo', 'Bo@Example.com')", "check"),
    ("INSERT INTO customer (full_name, email) VALUES ('Bo', 'not-an-email')", "check"),
    ("INSERT INTO customer (full_name, email) VALUES ('', 'bo@example.com')", "check"),
    ("INSERT INTO customer (email) VALUES ('bo@example.com')", "not-null"),
    ("INSERT INTO customer (full_name, email) VALUES ('Ada 2', 'ada@example.com')",
     "duplicate key"),
    ("INSERT INTO product (title, category, price, stock_count) VALUES ('Pie','pie',3,1)",
     "check"),
    ("INSERT INTO product (title, category, price, stock_count) VALUES ('Pie','cake',-3,1)",
     "check"),
    ("INSERT INTO review (rating, product_id) VALUES (6, 1)", "check"),
    ("INSERT INTO review (rating, product_id, customer_id) VALUES (4, 1, 1)", "duplicate key"),
    ("INSERT INTO order_line VALUES (1, 99, 1, 1)", "foreign key"),
    ("INSERT INTO order_line VALUES (1, 1, 0, 1)", "check"),
    ("INSERT INTO customer (customer_id, full_name, email) VALUES (7, 'Cy', 'cy@x.io')",
     "GENERATED ALWAYS"),
])
def test_the_database_enforces_the_rules(bakery, statement, error):
    _, schema = bakery
    seed(schema)
    rejects(schema, statement, error)


def test_on_delete_rules(bakery):
    _, schema = bakery
    seed(schema)
    rejects(schema, "DELETE FROM customer", "foreign key")  # restrict: has an order
    rejects(schema, "DELETE FROM product", "foreign key")  # restrict: on an order line
    sql(schema, "DELETE FROM customer_order")  # cascade: its lines go too
    assert sql(schema, "SELECT count(*) FROM order_line").strip() == "0"
    sql(schema, "DELETE FROM customer")  # set null: the review stays, unlinked
    assert sql(schema, "SELECT count(*) FROM review WHERE customer_id IS NULL").strip() == "1"


def test_every_link_is_indexed(bakery):
    _, schema = bakery
    out = sql(schema, "SELECT indexdef FROM pg_indexes WHERE schemaname = current_schema()")
    for table, column in [("customer_order", "customer_id"), ("order_line", "product_id"),
                          ("review", "customer_id")]:
        assert f"ON {schema}.{table} USING btree ({column})" in out


def test_deploy_refuses_to_overwrite_and_replace_starts_over(bakery, capsys):
    path, schema = bakery
    seed(schema)
    assert cli.main(["deploy", str(path), "--db", DB]) == 1
    assert "already exists" in capsys.readouterr().err
    assert cli.main(["deploy", str(path), "--db", DB, "--replace",
                     "--erd", str(path.with_suffix(".md"))]) == 0
    assert sql(schema, "SELECT count(*) FROM customer").strip() == "0"


def test_a_failing_script_leaves_nothing_behind(tmp_path):
    schema = f"t_{uuid.uuid4().hex[:12]}"
    s = dict(copy.deepcopy(EXAMPLE), name=schema)
    script = ddl.render(model.build(s), schema)
    broken = script.replace("COMMIT;", "SELECT 1/0;\nCOMMIT;")
    with pytest.raises(db.DatabaseError, match="division by zero"):
        db.deploy(DB, broken)
    assert not db.schema_exists(DB, schema)


def test_erd_command_reads_a_live_schema(bakery, capsys):
    _, schema = bakery
    capsys.readouterr()
    assert cli.main(["erd", "--db", DB, "--schema", schema]) == 0
    assert "erDiagram" in capsys.readouterr().out
    assert cli.main(["erd", "--db", DB, "--schema", "no_such_schema"]) == 1
