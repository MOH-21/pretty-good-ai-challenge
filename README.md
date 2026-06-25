# Voice Patient Bot

A Python voice bot that calls the Pretty Good AI voice agent (`+1-805-439-8008`),
role-plays as 10 different realistic patients, and captures **both sides** of each
call as audio and transcript — to surface bugs and quality issues in the agent
under test.

Built for the Pretty Good AI Engineering Challenge.

## Quick start

```bash
# 1. Set up the environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env
# Edit .env — fill in VAPI_API_KEY, VAPI_PHONE_NUMBER_ID, GOOGLE_AI_STUDIO_KEY
# (TARGET_PHONE_NUMBER is already set to the agent under test)

# 3. Make sure ffmpeg is installed (used to convert recordings to mp3)
ffmpeg -version   # apt install ffmpeg  /  brew install ffmpeg

# 4. Run the full batch of 10 calls
python run.py --all

# ...or run a single scenario
python run.py B1
```

Output lands in `outputs/` — one `.mp3` recording and one `.json` transcript per
scenario. The transcript JSON holds both the plain text and the structured,
speaker-labeled `messages[]` (patient vs. agent turns).

## How it works

The bot uses a **managed voice orchestrator (Vapi)** rather than hand-building the
real-time audio pipeline. Vapi owns the latency-sensitive speech loop; we own the
patient brain (the prompt/persona) and the call-running script.

```
run.py (CLI)
  ├─ loads scenario JSON from scenarios/
  ├─ patient_prompt.py builds a system prompt from the scenario
  ├─ vapi_client.py creates an outbound call via Vapi REST API
  │     Vapi handles: Deepgram Nova STT → Gemini Flash-Lite (text) → Deepgram Aura TTS
  └─ polls until the call ends → downloads recording + transcript → saves to outputs/
```

Gemini Flash-Lite (the patient brain) is wired through Vapi's custom-LLM provider
using Google AI Studio's OpenAI-compatible endpoint — keeping the LLM **free**
(Flash-Lite free tier) while Vapi's managed pipeline handles real-time audio.
Telephony is a **free Vapi-provided number** (Twilio underneath); no separate
Twilio account is required.

All 10 scenarios are pure JSON **data** (persona, objective, probes, voice) —
adding or tweaking a call means editing a config file, not code.

**Quality bar:** a call passes when the patient's turns land with p50 response
latency < 1.5s and no audible dead air > 2s, the audio is intelligible, and the
patient stays in character. This is the target we listen against while tuning —
the workflow is fire one call → listen → adjust (prompt, or swap Aura→ElevenLabs
for a robotic voice) → repeat, then run the full batch for submission.

## Dry-run before dialing

Real calls cost money, so validate a scenario as a **text** conversation first:

```bash
python dryrun.py B1     # or --all
```

This runs the *real* patient prompt (same Gemini model as the live call) against
a mock clinic agent and prints the transcript — no Vapi, no telephony, ~a cent.
Read it and confirm the patient stays in character, pursues its objective, and
fires its probe. Then place the real call with `python run.py B1`.

## The 10 scenarios

**Baseline (4)** — does the agent handle the happy path?

| ID | Scenario |
|----|----------|
| B1 | Book a routine new-patient appointment |
| B2 | Reschedule an existing appointment |
| B3 | Straightforward medication refill |
| B4 | Info question — hours / location / insurance |

**Edge cases (6)** — each engineered to break something specific.

| ID | Scenario | Failure mode hunted |
|----|----------|---------------------|
| E1 | Ask for a Sunday / holiday appointment | Office-hours awareness |
| E2 | Give a DOB, then change it mid-call | State tracking vs. stale value |
| E3 | Vague "I need to come in soon-ish" | Clarifying questions vs. inventing specifics |
| E4 | Interrupt / barge-in + abrupt topic switch | Turn-taking robustness (best-effort) |
| E5 | Early controlled-substance refill request | Guardrails + human escalation |
| E6 | Calling for a family member, wrong info | Identity verification + privacy |

## Project layout

```
run.py              CLI entrypoint (per-scenario or --all)
vapi_client.py      Thin Vapi REST wrapper: start_call / wait_for_completion / fetch_artifacts
patient_prompt.py   build_prompt(scenario) -> system prompt (pure, deterministic)
scenarios/*.json    10 scenario configs as data
tests/              No-network tests (prompt output + scenario schema)
outputs/            Recordings (.mp3) + transcripts (.json) land here
docs/superpowers/   Design spec
```

## Cost

Per call (~2 min): Vapi ~$0.10 + Deepgram speech ~$0.04 + Twilio ~$0.03 + Gemini
(free) ≈ **~$0.17/call**. The full batch of ~12 calls is roughly **$2**, leaving
ample headroom under the $20 budget for re-runs and tuning.

## Running tests

```bash
pip install pytest
pytest -q
```

No API keys or network needed — 17 deterministic schema + prompt validations.
