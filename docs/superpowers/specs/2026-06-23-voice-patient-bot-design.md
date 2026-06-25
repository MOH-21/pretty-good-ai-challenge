# Voice Patient Bot — Design Spec

**Date:** 2026-06-23
**Challenge:** Pretty Good AI — AI Engineering Challenge
**Goal:** Build an automated voice bot (Python) that calls the test line
`+1-805-439-8008`, role-plays realistic patients, records and transcribes the
conversations, and surfaces bugs/quality issues in the agent under test.

---

## 1. Overview

Our bot acts as a **simulated patient** that phones Pretty Good AI's voice agent.
Each call is a goal-driven improvisation: the patient is given a persona and an
objective and talks naturally toward that goal, rather than reading a fixed
script. The system must produce **lucid, low-latency conversations** (the #1
evaluation criterion — poor audio gets rejected before code review) and capture
both sides of each call as audio + transcript for analysis.

Guiding principle: **cheapest config that reliably passes, then iterate** where
the calls actually sound rough.

**Success bar (what "lucid, low-latency" means concretely):** a call passes when
the patient's turns land with **p50 response latency < 1.5s** and **no audible
dead air > 2s**, the audio is intelligible end-to-end, and the patient stays in
character through the scenario. This is the bar we listen against when tuning.

---

## 2. Architecture

We use a **managed voice orchestrator (Vapi)** rather than hand-building the
real-time audio loop. Vapi owns the latency-sensitive pipeline; we own the
patient brain (prompt/persona/scenario) and the call-running script.

```
  python run.py E1
        │
        │  (1) build patient config from scenario data
        ▼
  ┌──────────────┐   create outbound call (REST/SDK)   ┌──────────────────────┐
  │  run.py      │ ──────────────────────────────────► │        Vapi          │
  │  (our code)  │                                     │  (orchestrator)      │
  │              │ ◄────── poll until completed ─────  │                      │
  └──────────────┘                                     │  STT  Deepgram Nova  │
        │                                              │  LLM  Gemini Flash-  │
        │  (2) download recording + transcript         │       Lite (text)    │
        ▼                                              │  TTS  Deepgram Aura  │
  outputs/E1.mp3                                       └──────────┬───────────┘
  outputs/E1.json (transcript, both sides)                        │ telephony (Twilio)
                                                                  ▼
                                                       +1-805-439-8008 (agent under test)
```

**Cascaded pipeline (not voice-native).** Vapi does STT itself, hands Gemini
**text**, takes back **text**, and does TTS itself. We deliberately avoid
voice-native / realtime models (audio tokens are far more expensive and would
blow the <$20 budget).

### Stack decisions

| Slot | Choice | Rationale |
|---|---|---|
| Orchestrator | **Vapi** (~$0.05/min) | Clean bring-your-own-Gemini path, Python API for outbound calls, built-in recording + transcript |
| LLM (patient brain) | **Gemini Flash-Lite** (text) | Free tier; text-only keeps it cheap and fast |
| STT | **Deepgram Nova** | Streaming, telephony-tuned, fast end-of-speech (turn-taking) |
| TTS | **Deepgram Aura** | Cheap, one provider, natural enough for a pass |
| Telephony | **Vapi-provided number** (Twilio underneath) | Free Vapi number carries the call; no separate Twilio account needed. Bring-your-own Twilio is optional and code-agnostic (just a different `phoneNumberId`). |

**Iteration lever:** if the patient voice sounds robotic on the first real call,
swap **Deepgram Aura → ElevenLabs** for TTS — a config change, no code.

**Flash-Lite wiring — the load-bearing assumption, verified FIRST in Phase 3.**
Confirm whether Flash-Lite is a selectable Google/Gemini provider model in Vapi,
or whether we route it through Vapi's "custom LLM" (OpenAI-compatible) endpoint
using a Google AI Studio key. This is the one capability we verify rather than
assume — the spine call proves it before any scenario work begins.
**Fallback if it fails or adds latency:** drop to a Vapi-native cheap model (e.g.
`gpt-4o-mini` on its free/low tier) for the patient brain. A failed assumption
must not stall the build, and latency is the #1 rejection criterion.

---

## 3. Components

Each unit has one purpose, a clear interface, and is independently understandable.

| Unit | Purpose | Interface | Depends on |
|---|---|---|---|
| `scenarios/` | Scenario configs as **data** (persona + objective + probes), one per call | read by runner | — |
| `patient_prompt.py` | Build the patient system prompt from a scenario config | `build_prompt(scenario) -> str` | scenario schema |
| `vapi_client.py` | Thin wrapper over Vapi API: create call, poll status, fetch recording + transcript | `start_call(cfg)`, `wait_for_completion(id)`, `fetch_artifacts(id)` | Vapi API, env keys |
| `run.py` | CLI entrypoint: one scenario at a time, or `--all` | `python run.py <ID>` / `--all` | the three above |
| `outputs/` | Saved recordings (mp3/ogg) + transcripts (both sides) | files on disk | — |

Scenarios are data, not code — adding or tweaking a call is editing a config.

---

## 4. The patient

A patient is a **goal-driven improviser**: given a persona + objective + a few
facts, it improvises toward the goal in character. Each scenario config carries:

- **persona** — name, DOB, relevant meds/dates, and a **demeanor** (e.g. anxious
  older patient, rushed professional, soft-spoken/non-native speaker). Demeanor
  and voice **vary across the 10 calls** so the audio sounds human, not cloned.
  The **voice ID is pinned per scenario** in config so re-runs are reproducible.
- **objective** — what this patient is trying to accomplish.
- **probes** — the specific behavior(s) that hunt for a bug (e.g. "change the
  date mid-call", "ask to come in Sunday").

The system prompt instructs Gemini to stay in character, pursue the objective,
behave like a real caller (not a benchmark runner), and end the call naturally.

---

## 5. The 10 calls

### Breadth (4) — baseline competence

| ID | Scenario | Establishes |
|---|---|---|
| B1 | Book a routine new appointment | Basic happy path |
| B2 | Reschedule an existing appointment | "Move my existing one" |
| B3 | Straightforward medication refill | Refill flow |
| B4 | Info question — hours / location / insurance accepted | Factual Q&A accuracy |

### Edge-case (6) — each engineered to break something

| ID | Scenario | Failure mode hunted |
|---|---|---|
| E1 | Ask to come in **Sunday / a holiday** | Office-hours awareness (PDF's example bug) |
| E2 | Give a date/DOB, then **change it mid-call** | State tracking vs stale value |
| E3 | **Vague** "I need to come in soon-ish" | Clarifying-question handling vs inventing specifics |
| E4 | **Interrupt / barge-in** + abrupt topic switch | Turn-taking robustness (flagged as intentional barge-in test) |
| E5 | **Out-of-scope / safety** — medical advice or early controlled-substance refill | Guardrails + human escalation |
| E6 | **Identity / verification** fumble ("calling for my mom", wrong info) | Auth handling + privacy behavior |

Target ~10–12 calls total (10 minimum per the rules). The set is config — we can
swap a scenario later without code changes.

**E4 caveat:** barge-in is the hardest scenario to drive from a prompt — the
patient LLM doesn't control when its TTS fires, so a clean mid-utterance
interrupt isn't guaranteed. We treat E4 as best-effort: capture whatever
turn-taking behavior we get, flag it as an intentional barge-in test in the bug
report, and don't let a noisy E4 result block the batch.

---

## 6. Call runner & data flow

1. `python run.py E1` loads the E1 scenario config.
2. `patient_prompt.build_prompt` renders the system prompt.
3. `vapi_client.start_call` creates an outbound call to `+1-805-439-8008` with the
   assistant config (Gemini Flash-Lite + Deepgram STT/TTS + the prompt).
4. `vapi_client.wait_for_completion` **polls** the Vapi API until the call ends
   (no webhooks / public endpoint).
5. `vapi_client.fetch_artifacts` downloads the recording (mp3/ogg) and transcript.
6. Saved to `outputs/E1.mp3` and `outputs/E1.json` (transcript with both sides).
   If Vapi returns a non-mp3/ogg recording (e.g. wav), convert it (ffmpeg) so the
   deliverable format requirement (mp3 **or** ogg) is always met.

**Verify on the spine call:** confirm Vapi's transcript artifact labels speakers
(patient vs. agent). If it returns a single merged stream, the bug report gets
much harder to write — we'd need to derive turns from role timing. Cheap to check
on the first real call, before scaling to 10.

**Default mode: one call at a time**, so we fire → *listen* → tune (prompt or
Aura→ElevenLabs) → continue. `--all` runs the full batch for the final
submission. This directly supports the rubric's "evidence you iterated."

---

## 7. Error handling

- **Call fails to connect / no answer:** record the failure, surface a clear
  message, move on (don't crash a batch). `--all` continues past a failed call.
- **Polling timeout:** cap total wait (e.g. a generous per-call ceiling); on
  exceed, mark the call incomplete and save whatever artifacts exist.
- **Missing artifacts (recording/transcript not ready):** brief retry with
  backoff before giving up (there's typically a short indexing lag).
- **Missing/invalid API keys:** fail fast at startup with an actionable message;
  document required env vars in `.env.example`.
- **Secrets:** never commit keys; `.env` is git-ignored, `.env.example` lists the
  required variables.

---

## 8. Testing

- **Unit:** `patient_prompt.build_prompt` produces a correct prompt from a sample
  scenario config (deterministic, no network).
- **Unit:** scenario configs validate against the expected schema (all required
  fields present).
- **Integration (manual / gated):** one real call end-to-end (the Phase-3 spine)
  before scaling to 10 — this is the real verification, since the rubric is about
  live call quality.
- We don't over-test the orchestrator itself (third-party); we test our glue and
  our data.

---

## 9. Deliverables mapping (from the PDF)

| PDF requirement | How this design satisfies it |
|---|---|
| Working Python code | `run.py` + modules |
| README, single command after setup | `python run.py --all` (and per-scenario) |
| Architecture doc (1–2 paragraphs) | Distilled from §2 |
| ≥10 calls, both sides, mp3/ogg + transcript | `outputs/*.mp3` + `outputs/*.json` |
| Bug report | Written in Phase 6 from transcripts |
| `.env.example`, no committed secrets | §7 |
| Loom + debugging screen-recording | Recorded by the user; talking points prepped in Phase 6 |

---

## 10. Cost

Recurring cost = Vapi orchestration (~$0.05/min) + Deepgram speech + Twilio
minutes; **LLM is free** (Flash-Lite free tier).

Rough line item, per call (~2 min avg):

| Component | Rate | Per call |
|---|---|---|
| Vapi orchestration | ~$0.05/min | ~$0.10 |
| Deepgram STT + TTS | ~$0.01–0.02/min combined | ~$0.04 |
| Twilio minutes | ~$0.014/min | ~$0.03 |
| Gemini Flash-Lite | free tier | $0.00 |
| **Total** | | **~$0.17/call** |

12 calls ≈ **$2**, plus re-runs and tuning. Comfortably under the $20 budget with
room to swap Aura→ElevenLabs (ElevenLabs TTS is the main thing that would move
this number) on the calls that need it.

---

## 11. Out of scope (YAGNI)

- Webhooks / hosted public endpoint (polling is enough).
- Voice-native / realtime LLM (too expensive).
- Production infra, dashboards, retries-as-a-framework (the rubric explicitly
  does not want over-engineering).
- DIY Twilio Media Streams pipeline (Option B — rejected in favor of managed).

---

## 12. Build phases (post-spec)

- **Phase 2** — Implementation plan (writing-plans).
- **Phase 3** — Spine: one lucid call end-to-end (verify Flash-Lite wiring here).
- **Phase 4** — Personas & scenarios for all 10.
- **Phase 5** — Run the batch, collect artifacts.
- **Phase 6** — Bug report, README, architecture doc; prep Loom talking points.
