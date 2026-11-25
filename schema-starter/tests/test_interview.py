import json

import pytest
from schema_starter import __main__ as cli
from schema_starter.interview import interview, parse_attribute
from schema_starter.spec import check


def scripted(answers):
    it = iter(answers)
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return next(it)
    return ask, asked


SESSION = [
    "Corner Gym",                       # business
    "member, class, Order",             # things (Order is reserved)
    "A person with a membership",       # member description
    "full_name text required",
    "email email required unique",
    "phone text many",
    "",
    "",                                 # class: no description
    "title text required unique",
    "level choice:beginner|advanced required",
    "",
    "",                                 # customer_order: no description
    "total money required",
    "",
    "",                                 # member belongs to nothing
    "",                                 # class belongs to nothing
    "member",                           # customer_order belongs to member
    "",                                 #   must have one? default yes
    "d",                                #   delete member -> delete orders
    "member-class",                     # pairs
    "rating rating:1-10",
    "",
]


def test_a_whole_session_makes_a_valid_spec():
    ask, _ = scripted(SESSION)
    said = []
    s = interview(ask, said.append)
    check(s)
    assert s["name"] == "corner_gym"
    # 'class' is fine in PostgreSQL (not a reserved word); 'order' is not
    assert [e["name"] for e in s["entities"]] == ["member", "class", "customer_order"]
    assert any("'Order' will be called 'customer_order'" in line for line in said)
    member = s["entities"][0]
    assert member["description"] == "A person with a membership"
    assert {"name": "phone", "type": "text", "many": True} in member["attributes"]
    assert s["relationships"][0] == {"type": "belongs_to", "child": "customer_order",
                                     "parent": "member", "required": True,
                                     "on_delete": "cascade"}
    pair = s["relationships"][1]
    assert pair["between"] == ["member", "class"]
    assert pair["attributes"] == [{"name": "rating", "type": "rating", "min": 1, "max": 10}]


def test_bad_lines_are_explained_and_asked_again():
    answers = ["shop", "thing", "", "price dollars", "price money required", "", ]
    ask, _ = scripted(answers)
    said = []
    s = interview(ask, said.append)
    assert any("unknown type 'dollars'" in line for line in said)
    assert s["entities"][0]["attributes"] == [{"name": "price", "type": "money",
                                               "required": True}]


def test_a_required_link_cant_be_kept_unlinked():
    answers = ["shop", "author, book", "", "", "", "", "", "author", "y", "k", "b", ""]
    ask, _ = scripted(answers)
    said = []
    s = interview(ask, said.append)
    assert any("choose one of the letters" in line for line in said)
    assert s["relationships"][0]["on_delete"] == "restrict"


@pytest.mark.parametrize("line, expected", [
    ("price money required", {"name": "price", "type": "money", "required": True}),
    ("size choice:s|m|l", {"name": "size", "type": "choice", "choices": ["s", "m", "l"]}),
    ("age integer:0-130", {"name": "age", "type": "integer", "min": 0, "max": 130}),
    ("tag text many unique", {"name": "tag", "type": "text", "many": True, "unique": True}),
])
def test_parse_attribute(line, expected):
    assert parse_attribute(line) == expected


@pytest.mark.parametrize("line, message", [
    ("price", "name and a type"), ("price dollars", "unknown type"),
    ("size choice", "lists its values"), ("stars rating:5-1", "low-high"),
    ("note text:x", "doesn't take"), ("note text optional", "unknown word"),
    ("Order text", "lower_snake_case"),
])
def test_parse_attribute_errors(line, message):
    with pytest.raises(ValueError, match=message):
        parse_attribute(line)


def test_init_writes_the_spec_file(tmp_path, monkeypatch, capsys):
    ask, _ = scripted(SESSION)
    monkeypatch.setattr("builtins.input", ask)
    out = tmp_path / "gym.json"
    assert cli.main(["init", "-o", str(out)]) == 0
    check(json.loads(out.read_text()))
    assert "deploy" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", scripted(SESSION)[0])
    assert cli.main(["init", "-o", str(out)]) == 1  # won't overwrite without --force
