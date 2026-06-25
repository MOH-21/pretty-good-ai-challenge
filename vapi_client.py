"""
vapi_client.py — thin functions over the Vapi REST API.

Uses requests (NOT the Vapi SDK). Polls for call completion (no webhooks).
Handles: start outbound call, wait for completion, fetch recording + transcript.
"""

import os
import time
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

VAPI_BASE = "https://api.vapi.ai"
VAPI_API_KEY = os.getenv("VAPI_API_KEY")
VAPI_PHONE_NUMBER_ID = os.getenv("VAPI_PHONE_NUMBER_ID")
GOOGLE_AI_STUDIO_KEY = os.getenv("GOOGLE_AI_STUDIO_KEY")
TARGET_PHONE_NUMBER = os.getenv("TARGET_PHONE_NUMBER")

# Flash-Lite is the cheapest Gemini model; exact model string may need updating.
GEMINI_MODEL = "gemini-2.5-flash-lite"


def _check_keys():
    """Fail fast with a clear message if required env vars are missing."""
    missing = []
    if not VAPI_API_KEY:
        missing.append("VAPI_API_KEY")
    if not VAPI_PHONE_NUMBER_ID:
        missing.append("VAPI_PHONE_NUMBER_ID")
    if not GOOGLE_AI_STUDIO_KEY:
        missing.append("GOOGLE_AI_STUDIO_KEY")
    if not TARGET_PHONE_NUMBER:
        missing.append("TARGET_PHONE_NUMBER")
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Copy .env.example to .env and fill in the values."
        )


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json",
    }


def ensure_google_credential():
    """
    Make sure the Vapi org has a Google credential so the native `google` model
    provider can authenticate. Idempotent: creates one from GOOGLE_AI_STUDIO_KEY
    only if none exists. Lets `python run.py` work from a fresh Vapi account.
    """
    r = requests.get(f"{VAPI_BASE}/credential", headers=_headers(), timeout=30)
    r.raise_for_status()
    creds = r.json()
    if any(c.get("provider") == "google" for c in creds):
        return
    requests.post(
        f"{VAPI_BASE}/credential",
        headers=_headers(),
        json={"provider": "google", "apiKey": GOOGLE_AI_STUDIO_KEY},
        timeout=30,
    ).raise_for_status()
    logger.info("Created Vapi Google credential for native Gemini access.")


def start_call(scenario: dict, prompt: str) -> str:
    """
    Create an outbound call via Vapi.

    Returns the call ID (string).
    """
    _check_keys()
    ensure_google_credential()

    body = {
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {
            "number": TARGET_PHONE_NUMBER,
        },
        "assistant": {
            # No firstMessage — let the callee (Pretty Good AI agent) greet first.
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-3",
                "language": "en",
            },
            "voice": {
                "provider": "deepgram",
                "voiceId": scenario["voice_id"],
            },
            # Native Google provider: Vapi formats Gemini requests itself and
            # authenticates via the org's stored Google credential (ensured
            # above). Avoids the OpenAI-compat translation that Google's endpoint
            # rejected with a 400.
            "model": {
                "provider": "google",
                "model": GEMINI_MODEL,
                "messages": [
                    {"role": "system", "content": prompt},
                ],
            },
            "recordingEnabled": True,
            # Default recording format is wav/l16; we convert later if needed.
        },
    }

    resp = requests.post(f"{VAPI_BASE}/call", headers=_headers(), json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # The create response can be a single Call or a CallBatchResponse.
    # We always send a single call, so we expect a Call with an id.
    call_id = data.get("id")
    if not call_id:
        raise RuntimeError(f"Vapi create call response missing 'id': {data}")

    logger.info(f"Call started: {call_id}")
    return call_id


def wait_for_completion(call_id: str, timeout: int = 600) -> str:
    """
    Poll GET /call/{id} until status is 'ended'. Returns the final status.

    `timeout` is in seconds. Default 600s = 10 min is generous for a ~2 min call.
    """
    _check_keys()

    deadline = time.time() + timeout
    poll_interval = 3  # seconds

    while time.time() < deadline:
        resp = requests.get(
            f"{VAPI_BASE}/call/{call_id}", headers=_headers(), timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")

        if status == "ended":
            logger.info(f"Call {call_id} ended: {data.get('endedReason', 'unknown')}")
            return status

        logger.debug(f"Call {call_id} status: {status} (polling…)")
        time.sleep(poll_interval)
        # Gradually increase poll interval to be gentle on the API.
        poll_interval = min(poll_interval + 1, 10)

    raise TimeoutError(
        f"Call {call_id} did not end within {timeout}s. "
        f"Last known status: {status if 'status' in dir() else 'unknown'}"
    )


def fetch_artifacts(call_id: str):
    """
    Fetch the recording (as bytes) and transcript (as dict) for a completed call.

    Returns (recording_bytes: bytes | None, transcript: dict | None).

    recording_bytes is None if the recording URL is not available.
    transcript is None if not available.
    """
    _check_keys()

    resp = requests.get(
        f"{VAPI_BASE}/call/{call_id}", headers=_headers(), timeout=30
    )
    resp.raise_for_status()
    data = resp.json()

    artifact = data.get("artifact", {}) or {}

    # --- Recording ---
    # Vapi's recording field has shifted across API versions. Try the known
    # variants in order: flat legacy string, then the nested recording object.
    recording = artifact.get("recording") or {}
    recording_url = (
        artifact.get("recordingUrl")
        or (recording.get("combinedUrl") if isinstance(recording, dict) else None)
        or (recording.get("stereoUrl") if isinstance(recording, dict) else None)
        or (recording if isinstance(recording, str) else None)
    )
    recording_bytes = None
    if recording_url:
        r = requests.get(recording_url, timeout=60)
        r.raise_for_status()
        recording_bytes = r.content
        logger.info(
            f"Downloaded recording: {len(recording_bytes)} bytes "
            f"(content-type: {r.headers.get('content-type', 'unknown')})"
        )
    else:
        logger.warning(f"No recording URL found in artifact for call {call_id}")

    # --- Transcript ---
    # artifact.transcript is a plain concatenated string; the structured,
    # speaker-labeled turns (the "both sides" deliverable) live in messages[].
    # Save both so the transcript JSON is human-readable AND machine-parseable.
    transcript = {
        "transcript_text": artifact.get("transcript"),
        "messages": artifact.get("messages") or data.get("messages") or [],
    }

    return recording_bytes, transcript
