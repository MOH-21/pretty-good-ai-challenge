#!/usr/bin/env python3
"""
dryrun.py — validate a scenario as a TEXT conversation before spending a real call.

The patient side uses our real build_prompt() + the same Gemini model as the live
call, so the dry run tests the actual patient brain. The agent side is a mock
clinic scheduler (deliberately competent — we're stress-testing the patient, not
reproducing the real agent's bugs). Runs entirely on Google's text endpoint: no
Vapi, no telephony, no recording. Costs a fraction of a cent per scenario.

Usage:
    python dryrun.py B1      # simulate one scenario, print the transcript
    python dryrun.py --all   # simulate every scenario

Read the transcript and confirm, before dialing for real:
    1. patient stays in character (persona name, demeanor)
    2. patient pursues its objective
    3. the probe actually fires (e.g. E2 gives a wrong DOB then corrects it)
    4. patient ends the call naturally
"""

import sys
import json
import requests
from pathlib import Path

from patient_prompt import build_prompt
import os
from dotenv import load_dotenv

load_dotenv()

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
GEMINI_MODEL = "gemini-2.5-flash-lite"
GOOGLE_CHAT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
)

# Mock clinic agent — a competent scheduler. Competent on purpose: it gives the
# patient realistic openings to execute its probe (asks for DOB, states hours).
AGENT_SYSTEM = """You are the phone scheduling agent for a medical clinic.
Greet the caller, then help them. Collect the details a real clinic needs:
name, date of birth, reason for visit, and insurance. Office hours are
Monday–Friday, 8am–5pm (closed weekends and holidays). Offer specific weekday
appointment slots. Keep replies short and natural, like a real phone agent —
one or two sentences per turn."""


def gemini(messages: list) -> str:
    """One chat completion against Gemini (text only)."""
    key = os.getenv("GOOGLE_AI_STUDIO_KEY")
    if not key:
        raise RuntimeError("GOOGLE_AI_STUDIO_KEY missing — fill it in .env")
    r = requests.post(
        GOOGLE_CHAT_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": GEMINI_MODEL, "messages": messages},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _ended(text: str) -> bool:
    """Heuristic: did the patient wrap up the call?"""
    t = text.lower()
    return any(p in t for p in ("thank you, bye", "that's all i need", "goodbye", "have a good", "take care"))


def simulate(scenario: dict, turns: int = 8) -> list:
    """Run the patient (real prompt) against the mock agent. Returns transcript."""
    # Each side keeps its own chat history from its own point of view: the other
    # party's words arrive as "user", its own as "assistant".
    patient_msgs = [{"role": "system", "content": build_prompt(scenario)}]
    agent_msgs = [
        {"role": "system", "content": AGENT_SYSTEM},
        {"role": "user", "content": "(The phone rings and a caller connects.)"},
    ]
    transcript = []

    # Agent greets first (mirrors the real callee answering).
    agent_text = gemini(agent_msgs)
    agent_msgs.append({"role": "assistant", "content": agent_text})
    patient_msgs.append({"role": "user", "content": agent_text})
    transcript.append(("AGENT", agent_text))

    for _ in range(turns):
        patient_text = gemini(patient_msgs)
        patient_msgs.append({"role": "assistant", "content": patient_text})
        agent_msgs.append({"role": "user", "content": patient_text})
        transcript.append(("PATIENT", patient_text))
        if _ended(patient_text):
            break

        agent_text = gemini(agent_msgs)
        agent_msgs.append({"role": "assistant", "content": agent_text})
        patient_msgs.append({"role": "user", "content": agent_text})
        transcript.append(("AGENT", agent_text))

    return transcript


def dry_run(scenario_id: str):
    path = SCENARIOS_DIR / f"{scenario_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Scenario not found: {path}")
    scenario = json.loads(path.read_text())

    print(f"\n{'=' * 70}")
    print(f"DRY RUN — {scenario_id}: {scenario['title']}")
    print(f"Persona: {scenario['persona']['name']} ({scenario['persona']['demeanor']})")
    print(f"Objective: {scenario['objective']}")
    print(f"Probes: {scenario.get('probes', [])}")
    print(f"{'=' * 70}\n")

    for speaker, text in simulate(scenario):
        print(f"{speaker}: {text}\n")


def main():
    if len(sys.argv) < 2:
        ids = sorted(p.stem for p in SCENARIOS_DIR.glob("*.json"))
        print("Usage: python dryrun.py <SCENARIO_ID> | --all")
        print(f"Available: {', '.join(ids)}")
        sys.exit(1)

    if sys.argv[1] == "--all":
        for path in sorted(SCENARIOS_DIR.glob("*.json")):
            dry_run(path.stem)
    else:
        dry_run(sys.argv[1].upper())


if __name__ == "__main__":
    main()
