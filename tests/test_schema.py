from datetime import date, datetime

import pytest

from babel.schema import Entity, Field, Registry, SchemaError


def _registry():
    reg = Registry()
    reg.declare(Entity("customer", ("customer_id",), (
        Field("customer_id", "text"), Field("name", "text"),
    )))
    reg.declare(Entity("machine", ("machine_id",), (
        Field("machine_id", "text"),
        Field("customer_id", "text", ref="customer"),
        Field("critical", "bool"),
        Field("installed_on", "date", required=False),
        Field("power", "decimal", unit="kW"),
    )))
    return reg


def _machine(**over):
    row = {"machine_id": "BC-01", "customer_id": "C-100", "critical": True, "power": 15}
    row.update(over)
    return row


def test_accepts_a_row_that_fits_the_declaration():
    reg = _registry()
    rows, refusals = reg.clean("machine", [_machine()])
    assert refusals == []
    assert rows[0]["machine_id"] == "BC-01"
    assert rows[0]["installed_on"] is None


@pytest.mark.parametrize("row, code", [
    (_machine(extra="x"), "unknown_field"),
    (_machine(machine_id=None), "missing_field"),
    (_machine(critical=1), "wrong_type"),            # a number is not a flag
    (_machine(power=True), "wrong_type"),            # a flag is not a number
    (_machine(installed_on=datetime(2026, 1, 1)), "wrong_type"),  # a date, not a timestamp
    (_machine(machine_id="   "), "wrong_type"),      # blank text is refused
])
def test_refuses_rows_that_do_not_fit(row, code):
    rows, refusals = _registry().clean("machine", [row])
    assert rows == []
    assert [r.code for r in refusals] == [code]
    assert refusals[0].row_no == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_decimal_refuses_non_finite_numbers(value):
    # B1: a non-finite coordinate or quantity must not enter the record silently
    rows, refusals = _registry().clean("machine", [_machine(power=value)])
    assert rows == []
    assert [r.code for r in refusals] == ["non_finite"]
    assert refusals[0].row_no == 1


def test_duplicate_keys_keep_the_first_and_refuse_the_rest():
    rows, refusals = _registry().clean("machine", [_machine(), _machine(power=20)])
    assert len(rows) == 1
    assert rows[0]["power"] == 15
    assert [r.code for r in refusals] == ["duplicate_key"]


def test_dates_are_accepted_as_dates():
    rows, refusals = _registry().clean("machine", [_machine(installed_on=date(2020, 5, 1))])
    assert refusals == []


def test_references_must_exist_in_the_target_table():
    reg = _registry()
    tables = {
        "customer": [{"customer_id": "C-100", "name": "Sawmill"}],
        "machine": [_machine(), _machine(machine_id="CH-02", customer_id="C-999")],
    }
    refusals = reg.check_refs(tables)
    assert [(r.table, r.row_no, r.code) for r in refusals] == [("machine", 2, "unknown_reference")]


def test_undeclared_entities_and_fields_are_errors_not_guesses():
    reg = _registry()
    with pytest.raises(SchemaError) as err:
        reg.entity("invoice")
    assert err.value.code == "unknown_entity"
    with pytest.raises(SchemaError) as err:
        Entity("bad", ("missing",), (Field("name", "text"),))
    assert err.value.code == "bad_key"
    with pytest.raises(SchemaError) as err:
        Field("qty", "float")
    assert err.value.code == "unknown_type"
