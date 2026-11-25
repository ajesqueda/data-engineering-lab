import copy
import json
from pathlib import Path

import pytest
from schema_starter.spec import SpecError, check, suggest

EXAMPLE = json.loads((Path(__file__).parents[1] / "examples" / "bakery.json").read_text())


def spec(*entities, relationships=(), **extra):
    return {"name": "shop", "entities": list(entities),
            "relationships": list(relationships), **extra}


def entity(name, *attrs, **extra):
    return {"name": name, "attributes": list(attrs), **extra}


def attr(name, kind="text", **extra):
    return {"name": name, "type": kind, **extra}


def problems(s):
    with pytest.raises(SpecError) as info:
        check(s)
    return "\n".join(info.value.problems)


def test_the_example_is_valid():
    check(EXAMPLE)


@pytest.mark.parametrize("name, hint", [("order", "customer_order"), ("user", "app_user"),
                                        ("Order Items", "order_items"), ("2fa", "n_2fa")])
def test_unusable_names_get_a_suggestion(name, hint):
    assert hint in problems(spec(entity(name)))
    assert suggest(name) == hint


def test_every_problem_is_reported_at_once():
    found = problems(spec(entity("order", attr("price", "dollars")),
                          entity("item", attr("qty", "count", requird=True))))
    assert "reserved word" in found
    assert "unknown type 'dollars'" in found
    assert "unknown key 'requird'" in found


def test_repeating_group_is_not_1nf():
    found = problems(spec(entity("customer", attr("phone1"), attr("phone2"))))
    assert "repeating group (not in 1NF)" in found and '"many": true' in found
    found = problems(spec(entity("export", attr("book1_title"), attr("book2_title"))))
    assert "book1_title, book2_title" in found


def test_copying_a_parents_fact_is_not_3nf():
    s = spec(entity("customer", attr("email", "email")),
             entity("sale", attr("customer_email", "email")),
             relationships=[{"type": "belongs_to", "child": "sale", "parent": "customer"}])
    assert "sale.customer_email copies customer.email (not in 3NF)" in problems(s)


def test_copied_fact_is_caught_through_a_renamed_link():
    s = spec(entity("employee", attr("full_name")),
             entity("sale", attr("cashier_full_name")),
             relationships=[{"type": "belongs_to", "child": "sale", "parent": "employee",
                             "as": "cashier"}])
    assert "sale.cashier_full_name copies employee.full_name" in problems(s)


def test_copied_fact_on_a_pair_table_is_caught():
    s = copy.deepcopy(EXAMPLE)
    s["relationships"][-1]["attributes"].append(attr("product_title"))
    assert "order_line.product_title copies product.title" in problems(s)


def test_a_differently_named_fact_is_fine():
    # unit_price on the order line is the price at the time of sale, not product.price
    check(EXAMPLE)


def test_set_null_needs_an_optional_link():
    s = spec(entity("customer"), entity("sale"),
             relationships=[{"type": "belongs_to", "child": "sale", "parent": "customer",
                             "required": True, "on_delete": "set null"}])
    assert "'set null' can't keep a required link" in problems(s)


def test_two_links_to_the_same_parent_need_names():
    rel = {"type": "belongs_to", "child": "transfer", "parent": "account"}
    s = spec(entity("account"), entity("transfer"), relationships=[rel, dict(rel)])
    assert "use 'as'" not in problems(s) and "'as'" in problems(s)
    s["relationships"] = [dict(rel, **{"as": "source"}), dict(rel, **{"as": "target"})]
    check(s)


def test_self_link_needs_a_name():
    rel = {"type": "belongs_to", "child": "employee", "parent": "employee"}
    assert "already exists on employee" in problems(spec(entity("employee"),
                                                         relationships=[rel]))
    check(spec(entity("employee"), relationships=[dict(rel, **{"as": "manager"})]))


def test_required_links_in_a_circle_can_never_be_filled():
    rels = [{"type": "belongs_to", "child": "a_thing", "parent": "b_thing", "required": True},
            {"type": "belongs_to", "child": "b_thing", "parent": "a_thing", "required": True}]
    assert "go in a circle" in problems(spec(entity("a_thing"), entity("b_thing"),
                                             relationships=rels))
    rels[1]["required"] = False
    check(spec(entity("a_thing"), entity("b_thing"), relationships=rels))


def test_tables_cant_collide():
    s = spec(entity("customer", attr("phone", many=True)), entity("customer_phone"))
    assert "would be created twice" in problems(s)


def test_generated_columns_cant_be_attributes():
    assert "id column" in problems(spec(entity("customer", attr("customer_id", "integer"))))
    assert "added automatically" in problems(spec(entity("customer",
                                                         attr("created_at", "moment"))))
    check(spec(entity("customer", attr("created_at", "moment")), created_at=False))


@pytest.mark.parametrize("bad, message", [
    (attr("size", "choice"), "needs 'choices'"),
    (attr("size", "choice", choices=["s", "s"]), "lists a value twice"),
    (attr("stars", "rating", min=5, max=1), "smaller than 'max'"),
    (attr("stars", "rating", min=1.5), "whole number"),
    (attr("note", "text", min=1), "only apply to integer and rating"),
    (attr("note", "text", choices=["a"]), "only applies to the choice type"),
    (attr("note", "text", required="yes"), "true or false"),
    (attr("flags", "boolean", many=True), "yes/no"),
])
def test_attribute_rules(bad, message):
    assert message in problems(spec(entity("thing", bad)))


def test_many_to_many_rules():
    base = spec(entity("student"), entity("course"))
    pair = {"type": "many_to_many", "between": ["student", "course"]}
    check(dict(base, relationships=[pair]))
    assert "linked twice" in problems(dict(base, relationships=[pair, dict(pair)]))
    assert "linked to itself" in problems(dict(base, relationships=[
        {"type": "many_to_many", "between": ["student", "student"]}]))
    assert "'set null' isn't allowed" in problems(dict(base, relationships=[
        dict(pair, on_delete=["cascade", "set null"])]))
    assert "can't be 'many'" in problems(dict(base, relationships=[
        dict(pair, attributes=[attr("grade", many=True)])]))
    assert "clashes with a link column" in problems(dict(base, relationships=[
        dict(pair, attributes=[attr("student_id", "integer")])]))


def test_unique_together_names_attributes_or_links():
    s = copy.deepcopy(EXAMPLE)
    review = next(e for e in s["entities"] if e["name"] == "review")
    review["unique_together"] = [["product", "nobody"]]
    assert "names 'nobody'" in problems(s)
    review["unique_together"] = [["product"]]
    assert "two or more" in problems(s)


def test_unknown_relationship_and_missing_entities():
    found = problems(spec(entity("a_thing"), relationships=[
        {"type": "has_many"}, {"type": "belongs_to", "child": "a_thing", "parent": "ghost"}]))
    assert "'has_many'" in found and "'ghost' isn't one of the entities" in found


def test_not_an_object():
    assert "JSON object" in problems([])
    assert "at least one thing" in problems({"name": "shop"})
