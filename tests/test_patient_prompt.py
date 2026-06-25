"""
Tests for patient_prompt.build_prompt — deterministic, no network.
"""

from patient_prompt import build_prompt


SAMPLE_SCENARIO = {
    "id": "T1",
    "title": "Test scenario",
    "persona": {
        "name": "Alice Test",
        "dob": "1980-06-15",
        "demeanor": "friendly but tired",
        "facts": {
            "reason": "sore throat for 3 days",
            "insurance": "Aetna PPO",
        },
    },
    "objective": "Get a same-day appointment for a sore throat.",
    "probes": ["Check if agent asks about fever"],
    "voice_id": "aura-asteria-en",
}


def test_build_prompt_contains_persona_name():
    prompt = build_prompt(SAMPLE_SCENARIO)
    assert "Alice Test" in prompt


def test_build_prompt_contains_dob():
    prompt = build_prompt(SAMPLE_SCENARIO)
    assert "1980-06-15" in prompt


def test_build_prompt_contains_objective():
    prompt = build_prompt(SAMPLE_SCENARIO)
    assert "same-day appointment" in prompt.lower()
    assert "sore throat" in prompt.lower()


def test_build_prompt_contains_probe_in_behavioural_section():
    prompt = build_prompt(SAMPLE_SCENARIO)
    assert "BEHAVIOURAL NOTES" in prompt
    assert "fever" in prompt


def test_build_prompt_contains_rules():
    prompt = build_prompt(SAMPLE_SCENARIO)
    assert "RULES FOR THIS CALL" in prompt
    assert "REAL person" in prompt
    assert "End the call naturally" in prompt


def test_build_prompt_no_meta_commentary():
    """The prompt should instruct AGAINST meta-commentary, not include it."""
    prompt = build_prompt(SAMPLE_SCENARIO)
    # Should tell the LLM NOT to break character.
    assert "Never break character" in prompt


def test_build_prompt_handles_no_probes():
    scenario_no_probes = {**SAMPLE_SCENARIO, "probes": []}
    prompt = build_prompt(scenario_no_probes)
    # Should still produce a valid prompt without the probe section.
    assert "BEHAVIOURAL NOTES" not in prompt
    assert "RULES FOR THIS CALL" in prompt


def test_build_prompt_handles_empty_facts():
    scenario_no_facts = {
        **SAMPLE_SCENARIO,
        "persona": {**SAMPLE_SCENARIO["persona"], "facts": {}},
    }
    prompt = build_prompt(scenario_no_facts)
    assert "(none)" in prompt
