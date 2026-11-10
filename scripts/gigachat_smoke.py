"""Opt-in real GigaChat check using synthetic text only; never print credentials."""

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import httpx
from dotenv import load_dotenv

from app.ai.gigachat import GigaChatProvider, GigaChatRequestError, GigaChatSettings


SYNTHETIC_TEXT = (
    "Синтетическая запись самочувствия: сегодня я чувствую слабость, "
    "она появилась утром."
)


def check() -> dict[str, object]:
    settings = GigaChatSettings.from_env()
    provider = GigaChatProvider(settings)
    try:
        facts = provider.extract_facts(SYNTHETIC_TEXT)
        if not facts or not all(
            not fact.confirmed and fact.evidence in SYNTHETIC_TEXT for fact in facts
        ):
            raise RuntimeError("Live extraction did not produce unconfirmed grounded facts")
        result = {
            "synthetic": True,
            "model": settings.model,
            "live_extraction": "passed",
            "fact_count": len(facts),
            "schema_and_evidence_validation": "passed",
            "facts_remain_unconfirmed": True,
            "persistence": "not exercised by adapter smoke",
        }
        provider.settings = replace(settings, model="medsi-care-invalid-model-for-smoke")
        try:
            provider.extract_facts(SYNTHETIC_TEXT)
        except GigaChatRequestError as exc:
            if exc.status_code is None or exc.status_code < 400:
                raise RuntimeError("Expected an HTTP error for invalid model") from None
            result["live_invalid_model"] = {"result": "passed", "status_code": exc.status_code}
        else:
            raise RuntimeError("Invalid model was unexpectedly accepted")
    finally:
        provider.close()

    # Exercise actual network timeout handling with an intentionally tiny local
    # timeout. This is not evidence that the external service had an outage.
    timeout_provider = GigaChatProvider(replace(settings, timeout_seconds=0.000001))
    try:
        timeout_provider.extract_facts(SYNTHETIC_TEXT)
    except GigaChatRequestError as exc:
        if not isinstance(exc.__cause__, httpx.TimeoutException):
            raise RuntimeError("Expected an induced network timeout") from None
        result["induced_live_transport_timeout"] = "passed"
    else:
        raise RuntimeError("The induced timeout did not occur")
    finally:
        timeout_provider.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Local credentials file; never stored in result")
    parser.add_argument("--output", type=Path, help="New sanitized JSON report; refuses overwrite")
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("output exists; choose a new path")
    if args.env_file:
        if not args.env_file.is_file():
            parser.error("local environment file not found")
        load_dotenv(args.env_file, override=True)
    try:
        result = check()
    except Exception as exc:
        # Do not dump response bodies, env, headers or exception chains.
        print(json.dumps({"result": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
    root = Path(__file__).resolve().parents[1]
    result["checked_at_utc"] = datetime.now(timezone.utc).isoformat()
    result["git_commit"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    result["adapter_sha256"] = hashlib.sha256(
        (root / "backend/app/ai/gigachat.py").read_bytes()
    ).hexdigest()
    result["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result["working_tree_dirty"] = bool(subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=root, text=True,
    ).strip())
    result["provider_values_not_reproducible"] = True
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as output:
            output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
