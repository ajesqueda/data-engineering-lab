"""The standalone SVG diagram and the README / landing-page graphics."""

import importlib.util
import json
import re
from pathlib import Path
from xml.dom import minidom

import pytest
from schema_starter import __main__ as cli
from schema_starter import model, svg

TOOL = Path(__file__).parents[1]
EXAMPLE = json.loads((TOOL / "examples" / "bakery.json").read_text())
SITE = TOOL.parent / "docs" / "schema-starter"


def test_layers_follow_the_links():
    depth = svg.layers(model.build(EXAMPLE))
    assert depth["customer"] == depth["product"] == 0
    assert depth["customer_order"] == depth["review"] == depth["customer_phone"] == 1
    assert depth["order_line"] == 2  # it points at customer_order, which is in layer 1


def test_every_table_column_and_link_is_drawn():
    tables = model.build(EXAMPLE)
    doc = svg.render(tables, "bakery")
    minidom.parseString(doc)  # valid XML
    for t in tables:
        assert f">{t.name}</text>" in doc
    links = sum(len(t.foreign_keys) for t in tables)
    assert doc.count('class="link"') == links
    assert doc.count('class="ends"') == links
    assert ">customer_id?</text>" in doc  # review's optional link is marked


def test_still_svg_has_no_animation_and_motion_can_be_turned_off():
    assert "@keyframes" not in svg.render(model.build(EXAMPLE), animate=False)
    assert "prefers-reduced-motion" in svg.render(model.build(EXAMPLE))


def test_self_link_and_text_are_escaped():
    s = {"name": "org", "entities": [{"name": "employee"}], "relationships": [
        {"type": "belongs_to", "child": "employee", "parent": "employee", "as": "manager"}]}
    doc = svg.render(model.build(s), 'Org <"chart">')
    minidom.parseString(doc)
    assert "&lt;" in doc and doc.count('class="link"') == 1


def test_cli_writes_svg(tmp_path):
    out = tmp_path / "bakery.svg"
    assert cli.main(["erd", str(TOOL / "examples" / "bakery.json"), "-o", str(out)]) == 0
    minidom.parse(str(out))


def _assets():
    spec = importlib.util.spec_from_file_location("make_assets", TOOL / "assets" / "make_assets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("name", ["hero.svg", "terminal.svg", "erd.svg"])
def test_committed_graphics_are_valid_and_up_to_date(name):
    """Regenerate with: python assets/make_assets.py"""
    m = _assets()
    rows, spec = m.session()
    fresh = {"hero.svg": m.hero(),
             "terminal.svg": m.terminal(rows, len(model.build(spec)), spec["name"]),
             "erd.svg": svg.render(model.build(EXAMPLE), "bakery: data model")}[name]
    committed = (TOOL / "assets" / name).read_text()
    minidom.parseString(committed)
    assert committed == fresh, f"assets/{name} is stale: run python assets/make_assets.py"
    if name != "hero.svg":
        assert (SITE / name).read_text() == committed, f"docs copy of {name} is stale"


def test_terminal_shows_only_real_answers():
    m = _assets()
    rows, spec = m.session()
    shown = [answer for _, text, answer in rows if text == "›"]
    assert shown and all(a in m.ANSWERS for a in shown)
    assert spec["name"] == "corner_bakery"


def test_landing_page_uses_real_checker_messages():
    """The messages quoted on the page are the checker's own words."""
    from schema_starter.spec import SpecError, check
    page = (SITE / "index.html").read_text()
    bad = {"name": "salon", "entities": [
        {"name": "client", "attributes": [{"name": "email", "type": "email"},
                                          {"name": "phone1", "type": "text"},
                                          {"name": "phone2", "type": "text"}]},
        {"name": "appointment", "attributes": [{"name": "client_email", "type": "email"}]},
        {"name": "order"}],
        "relationships": [{"type": "belongs_to", "child": "appointment", "parent": "client"}]}
    with pytest.raises(SpecError) as info:
        check(bad)
    for message in info.value.problems:
        assert message.replace("'", "'") in page or message.split(":")[0] not in page, message
    quoted = re.findall(r"out: `([^`]*)`", page)
    real = info.value.problems + [
        "review belongs_to customer: 'set null' can't keep a required link; use restrict or "
        "cascade, or make the link optional"]
    for q in quoted:
        assert q in real, f"page quotes a message the checker doesn't produce: {q}"
