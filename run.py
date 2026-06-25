#!/usr/bin/env python3
"""
run.py — CLI entrypoint for the voice patient bot.

Usage:
    python run.py B1          # run a single scenario
    python run.py --all       # run all scenarios sequentially

Flow per scenario:
    load JSON → build prompt → start call → poll until done → fetch artifacts → save
"""

import sys
import os
import json
import subprocess
import logging
from pathlib import Path

from patient_prompt import build_prompt
from vapi_client import start_call, wait_for_completion, fetch_artifacts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run")

OUTPUTS_DIR = Path(__file__).resolve().parent / "outputs"
SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


def load_scenario(scenario_id: str) -> dict:
    """Load a scenario JSON file by ID (e.g. 'B1', 'E3')."""
    path = SCENARIOS_DIR / f"{scenario_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Scenario not found: {path}")
    with open(path) as f:
        return json.load(f)


def list_scenario_ids() -> list[str]:
    """Return all scenario IDs found in scenarios/."""
    ids = []
    for p in sorted(SCENARIOS_DIR.glob("*.json")):
        ids.append(p.stem)
    return ids


def save_artifacts(
    scenario_id: str,
    recording_bytes: bytes | None,
    transcript: dict | None,
):
    """
    Save recording as outputs/<ID>.mp3 (converting via ffmpeg if needed)
    and transcript as outputs/<ID>.json.
    """
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    # --- Save transcript ---
    if transcript is not None:
        transcript_path = OUTPUTS_DIR / f"{scenario_id}.json"
        with open(transcript_path, "w") as f:
            json.dump(transcript, f, indent=2)
        logger.info(f"Transcript saved: {transcript_path}")

    # --- Save recording ---
    if recording_bytes is not None:
        raw_path = OUTPUTS_DIR / f"{scenario_id}.raw_audio"
        mp3_path = OUTPUTS_DIR / f"{scenario_id}.mp3"

        with open(raw_path, "wb") as f:
            f.write(recording_bytes)

        # Convert to mp3 via ffmpeg (handles wav, ogg, or whatever Vapi returns).
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(raw_path),
                    "-codec:a", "libmp3lame", "-b:a", "128k",
                    str(mp3_path),
                ],
                capture_output=True,
                check=True,
            )
            raw_path.unlink()  # remove the raw temp file
            logger.info(f"Recording saved: {mp3_path}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning(
                f"ffmpeg conversion failed (is ffmpeg installed?): {e}\n"
                f"Raw recording left at: {raw_path}"
            )


def run_scenario(scenario_id: str):
    """Run a single scenario end-to-end."""
    logger.info(f"=== Starting scenario {scenario_id} ===")

    scenario = load_scenario(scenario_id)
    logger.info(f"  Title: {scenario['title']}")
    logger.info(f"  Persona: {scenario['persona']['name']}")

    prompt = build_prompt(scenario)
    call_id = start_call(scenario, prompt)
    logger.info(f"  Call ID: {call_id}")

    try:
        status = wait_for_completion(call_id, timeout=600)
        logger.info(f"  Final status: {status}")
    except TimeoutError as e:
        logger.error(f"  Timeout: {e}")
        # Still try to fetch whatever artifacts exist.
        status = "timeout"

    recording_bytes, transcript = fetch_artifacts(call_id)
    save_artifacts(scenario_id, recording_bytes, transcript)

    logger.info(f"=== Scenario {scenario_id} complete ===\n")
    return status


def main():
    if len(sys.argv) < 2:
        print("Usage: python run.py <SCENARIO_ID> | --all")
        print(f"Available scenarios: {', '.join(list_scenario_ids())}")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--all":
        scenario_ids = list_scenario_ids()
        logger.info(f"Running {len(scenario_ids)} scenarios: {scenario_ids}\n")

        results = {}
        for sid in scenario_ids:
            try:
                status = run_scenario(sid)
                results[sid] = status
            except Exception as e:
                logger.error(f"  FAILED: {sid} — {e}")
                results[sid] = "error"

        # Summary
        logger.info("=" * 50)
        logger.info("BATCH COMPLETE")
        for sid, st in results.items():
            logger.info(f"  {sid}: {st}")
        failed = [sid for sid, st in results.items() if st != "ended"]
        if failed:
            logger.warning(f"{len(failed)} call(s) did not end cleanly: {failed}")
        else:
            logger.info("All calls ended cleanly.")
    else:
        scenario_id = arg.upper()
        try:
            run_scenario(scenario_id)
        except Exception as e:
            logger.error(f"FAILED: {scenario_id} — {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
