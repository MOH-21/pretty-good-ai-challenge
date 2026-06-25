"""
Tests for scenario JSON files — validate schema, no network.
"""

import json
from pathlib import Path

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"

REQUIRED_TOP_KEYS = {"id", "title", "persona", "objective", "probes", "voice_id"}
REQUIRED_PERSONA_KEYS = {"name", "dob", "demeanor", "facts"}


def _all_scenarios():
    """Return list of (id, dict) for every scenario JSON file."""
    scenarios = []
    for p in sorted(SCENARIOS_DIR.glob("*.json")):
        with open(p) as f:
            scenarios.append((p.stem, json.load(f)))
    return scenarios


def test_at_least_10_scenarios():
    scenarios = _all_scenarios()
    assert len(scenarios) >= 10, f"Expected ≥10 scenarios, got {len(scenarios)}"


def test_each_scenario_has_required_top_keys():
    for sid, data in _all_scenarios():
        missing = REQUIRED_TOP_KEYS - set(data.keys())
        assert not missing, f"{sid}: missing top-level keys: {missing}"


def test_each_scenario_has_required_persona_keys():
    for sid, data in _all_scenarios():
        persona = data.get("persona", {})
        missing = REQUIRED_PERSONA_KEYS - set(persona.keys())
        assert not missing, f"{sid}: missing persona keys: {missing}"


def test_each_scenario_has_non_empty_title():
    for sid, data in _all_scenarios():
        assert data.get("title", "").strip(), f"{sid}: title is empty"


def test_each_scenario_has_non_empty_objective():
    for sid, data in _all_scenarios():
        assert data.get("objective", "").strip(), f"{sid}: objective is empty"


def test_each_scenario_has_voice_id():
    for sid, data in _all_scenarios():
        vid = data.get("voice_id", "")
        assert vid.startswith("aura-"), f"{sid}: voice_id '{vid}' doesn't look like an Aura voice"


def test_each_scenario_probes_is_list():
    for sid, data in _all_scenarios():
        assert isinstance(data.get("probes"), list), f"{sid}: probes is not a list"


def test_each_scenario_facts_is_dict():
    for sid, data in _all_scenarios():
        persona = data.get("persona", {})
        assert isinstance(persona.get("facts"), dict), f"{sid}: persona.facts is not a dict"


def test_all_10_expected_ids_present():
    ids = {sid for sid, _ in _all_scenarios()}
    expected = {"B1", "B2", "B3", "B4", "E1", "E2", "E3", "E4", "E5", "E6"}
    missing = expected - ids
    assert not missing, f"Missing expected scenarios: {missing}"
