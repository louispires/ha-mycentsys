"""Tests for the product mapping and status normalising. No Home Assistant needed."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "mycentsys_const",
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "mycentsys"
    / "const.py",
)
const = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(const)


def test_garage_products_use_the_sdo_activation_set():
    assert const.family_for_product(2) == const.FAMILY_GARAGE
    assert const.family_for_product(50) == const.FAMILY_GARAGE


def test_swing_products_are_recognised():
    for product in (30, 31, 32, 33, 45, 46, 47):
        assert const.family_for_product(product) == const.FAMILY_SWING


def test_unknown_products_fall_back_to_slider():
    assert const.family_for_product(1) == const.FAMILY_SLIDER
    assert const.family_for_product(999) == const.FAMILY_SLIDER


def test_swing_has_no_theft_alarm_buttons():
    keys = {a.key for a in const.OPTIONAL_ACTIVATIONS[const.FAMILY_SWING]}
    assert "arm_alarm" not in keys
    assert "pedestrian" in keys


def test_activation_keys_are_unique_within_a_family():
    for family, activations in const.OPTIONAL_ACTIVATIONS.items():
        keys = [a.key for a in activations]
        assert len(keys) == len(set(keys)), family


def test_status_name_accepts_numbers_and_csharp_names():
    assert const.status_name(2, const.OPERATOR_STATUS) == "closed"
    assert const.status_name("2", const.OPERATOR_STATUS) == "closed"
    assert const.status_name("PartlyOpen", const.OPERATOR_STATUS) == "partly_open"
    assert const.status_name("Closing", const.OPERATOR_STATUS) == "closing"


def test_status_name_handles_missing_values():
    assert const.status_name(None, const.OPERATOR_STATUS) is None
    assert const.status_name("", const.OPERATOR_STATUS) is None
    assert const.status_name(99, const.OPERATOR_STATUS) is None


def test_open_close_trigger_ids_match_the_app():
    assert const.TRG == 34
    assert const.PED == 35
    assert (const.SDO_RUN, const.SDO_OPEN_ONLY, const.SDO_CLOSE_ONLY) == (1, 5, 6)
