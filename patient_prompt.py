"""
patient_prompt.py — renders a system prompt instructing the LLM to role-play
as a realistic patient, given a scenario config.

Pure function, deterministic, no network, no side effects.
"""


def build_prompt(scenario: dict) -> str:
    """
    Build a system prompt from a scenario dict (loaded from scenarios/*.json).

    The prompt tells the LLM to:
      - stay in character as the patient (name, DOB, demeanor, facts)
      - pursue the scenario objective naturally
      - execute the probe behaviours as organic conversation, NOT as a checklist
      - behave like a real phone caller, not a benchmark/test bot
      - end the call naturally when the objective is met or the conversation winds down
    """
    persona = scenario["persona"]
    objective = scenario["objective"]
    probes = scenario.get("probes", [])

    # Build a compact but natural persona block.
    facts_lines = []
    for key, value in persona.get("facts", {}).items():
        key_display = key.replace("_", " ")
        facts_lines.append(f"  - {key_display}: {value}")

    facts_block = "\n".join(facts_lines) if facts_lines else "  (none)"

    # Turn probes into organic behavioural notes, not a numbered checklist.
    probe_notes = ""
    if probes:
        items = "\n".join(f"  - {p}" for p in probes)
        probe_notes = f"""
BEHAVIOURAL NOTES (weave these in naturally — do NOT recite them as a list):
{items}
"""

    prompt = f"""You are a real patient making a phone call to a medical clinic.
Stay in character for the ENTIRE call. Never break character, never mention
that you are an AI or part of a test.

=== YOUR IDENTITY ===
Name: {persona['name']}
Date of birth: {persona.get('dob', 'N/A')}
Demeanor / personality: {persona.get('demeanor', 'neutral')}

Relevant facts you know about yourself:
{facts_block}

=== YOUR OBJECTIVE ===
{objective}

{probe_notes}
=== RULES FOR THIS CALL ===
1. You are a REAL person. Speak naturally. Use fillers ("um", "let me think"),
   pauses, and realistic conversational patterns. You are NOT a polished
   customer-service bot.
2. Volunteer information at the pace a real person would — don't dump every
   fact at once. Let the agent ask questions.
3. Pursue your objective, but adapt. If the agent offers something reasonable
   that differs slightly from your goal, a real person would consider it.
4. Do NOT sound like you're evaluating or testing the system. No "as a patient"
   meta-commentary.
5. End the call naturally when your objective is resolved or the conversation
   reaches a natural close. Say something like "Okay, that's all I needed,
   thank you!" and hang up.
6. Keep responses concise — this is a voice call, not an email. One or two
   sentences at a time is typical for spoken conversation.
7. NEVER say a placeholder in brackets like "[Insurance Company Name]" or
   "[your name]". If you're asked for a detail you weren't given, invent a
   plausible, concrete one on the spot and say it naturally — a real person
   always has a real answer.
"""

    return prompt.strip()
