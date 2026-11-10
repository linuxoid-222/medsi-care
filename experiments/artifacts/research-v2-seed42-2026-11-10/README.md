# research-v2: frozen descriptive synthetic evaluation

Generated on 2026-11-10 from source commit `859b69581327a0f22d7f8ae75605fb83356c1b3e`.
100 profiles generated; 20 held-out profiles evaluated (560 person-days).
The archive is distinct from experiments/results/latest.json.

- result.json: config, split, versions, source SHA-256, evaluation counts,
  all held-out synthetic records, label-free predictions, extractions.
- figures/: three figures in PNG/SVG, generated solely from result.json.
- figures/manifest.json: JSON hash, figure hashes and plotting environment.
- SHA256SUMS: checksums of the saved artifacts.

See ../../../docs/RESEARCH.md for metric definitions, limitations and commands.
No clinical claims. One seed, 20 test profiles; statistical stability not established.
All test text templates overlap with train. No uncertainty facts in test.

Recompute from repository root:

```bash
.venv/bin/python -m experiments.verify_report experiments/artifacts/research-v2-seed42-2026-11-10/result.json
.venv/bin/python -m experiments.plot_results --result experiments/artifacts/research-v2-seed42-2026-11-10/result.json --output-dir /tmp/medsi-figures-replay-new
sha256sum -c experiments/artifacts/research-v2-seed42-2026-11-10/SHA256SUMS
```

Existing result/figure files are never replaced by archive mode. Use a new path.

SVG line-end whitespace from matplotlib was stripped for Git without visual changes.
Replays are numerically/visually reproducible; SVG metadata/IDs are not guaranteed
byte-identical between exports. Checksums verify this specific saved archive.
