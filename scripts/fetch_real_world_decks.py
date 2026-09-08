"""Fetch real-world PPTX benchmark decks from Apache POI test-data.

Sources decks that are genuinely authored by third-party tooling / real-world users
(not by this repository's own generators), so the fidelity benchmark is not
self-referential. Licensed under Apache License 2.0 (see REAL_WORLD_ORIGIN.md).

Usage:
    python scripts/fetch_real_world_decks.py

Idempotent: existing files with a matching SHA-256 are skipped.
"""

import hashlib
import ssl
import urllib.request
from pathlib import Path

BASE_URL = "https://raw.githubusercontent.com/apache/poi/trunk/test-data/slideshow/"

# Selected for structural variety: theme, table, chart, SmartArt, groups, media, masters.
DECKS = {
    "themes.pptx": "Theme-focused deck (10 slides / 212 parts)",
    "aascu.org_hbcu_leadershipsummit_cooper_.pptx": "Real 16-slide conference leadership deck",
    "table-with-theme.pptx": "Table styled with an active theme",
    "chart-slide-bg.pptx": "Slide with an embedded chart",
    "SmartArt.pptx": "SmartArt diagram slide",
    "sample_pptx_grouping_issues.pptx": "Nested grouping / coordinate-system issues",
    "placeholder-layout-color.pptx": "Placeholder and slide-layout/master coloring",
    "backgrounds.pptx": "Slide background / media usage",
}

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "assets" / "real_world"
ORIGIN_FILE = OUTPUT_DIR / "REAL_WORLD_ORIGIN.md"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_deck(name: str, ctx: ssl.SSLContext) -> bytes:
    url = BASE_URL + name
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        return resp.read()


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ctx = ssl.create_default_context()

    records = []
    for name, description in DECKS.items():
        target = OUTPUT_DIR / name
        if target.exists():
            digest = _sha256(target)
            print(f"[skip] {name} (already present, sha256={digest[:12]})")
            records.append((name, description, digest))
            continue

        print(f"[fetch] {name} ...")
        data = fetch_deck(name, ctx)
        if not data.startswith(b"PK"):
            raise RuntimeError(f"{name}: downloaded payload is not a valid OOXML zip (magic {data[:4]!r})")
        target.write_bytes(data)
        digest = _sha256(target)
        print(f"[ok]   {name} ({len(data)} bytes, sha256={digest[:12]})")
        records.append((name, description, digest))

    origin_lines = [
        "# Real-World Benchmark Decks",
        "",
        "These PPTX decks are real-world files authored independently of this repository's",
        "generators (they come from Apache POI's test corpus, originally collected from",
        "public presentations and Office tooling). They are used to de-bias the fidelity",
        "benchmark: the parser/builder must reconstruct content it did not author.",
        "",
        "## Source",
        "",
        f"- Repository: https://github.com/apache/poi",
        f"- Directory: `test-data/slideshow`",
        f"- Raw URL base: `{BASE_URL}`",
        "",
        "## License",
        "",
        "Apache POI is licensed under the Apache License 2.0. See",
        "https://www.apache.org/licenses/LICENSE-2.0 for the full license text.",
        "Redistributed here for test/benchmark purposes with attribution to the original",
        "authors and upstream sources of each file.",
        "",
        "## Files",
        "",
        "| File | Description | SHA-256 |",
        "| --- | --- | --- |",
    ]
    for name, description, digest in records:
        origin_lines.append(f"| `{name}` | {description} | `{digest}` |")
    origin_lines.append("")

    ORIGIN_FILE.write_text("\n".join(origin_lines), encoding="utf-8")
    print(f"\nWrote provenance manifest: {ORIGIN_FILE}")


if __name__ == "__main__":
    main()