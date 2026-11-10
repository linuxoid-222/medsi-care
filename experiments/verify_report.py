"""Recompute a saved research report and check its source fingerprint."""

import argparse
import hashlib
import json
from pathlib import Path

from experiments.run_experiment import run


def verify(path: Path) -> None:
    report = json.loads(path.read_text())
    root = Path(__file__).resolve().parents[1]
    for name, expected in report["provenance"]["source_sha256"].items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"source fingerprint differs: {name}; use the archived commit")
    config = report["config"]
    recomputed = json.loads(json.dumps(run(
        config["profile_count"], config["days"], report["seed"], config["test_fraction"]
    )))
    expected = {key: value for key, value in report.items() if key != "provenance"}
    if recomputed != expected:
        raise ValueError("recomputed result differs from archive")
    print("PASS: source hashes, split, records, predictions, extractions and all metrics match")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    verify(parser.parse_args().result)
