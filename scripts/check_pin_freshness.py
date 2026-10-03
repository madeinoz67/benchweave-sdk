#!/usr/bin/env python3
"""Compare the [server] extra's ui-html pin to the package index (freshness).

The freshness half of the renderer pin discipline (PRD 12 Q5, gateway
obligation 12; issue #294 slice 1, design §2.2). The pin's integrity is
already machine-checked (uv sync --locked in CI; the package verifier at
build_app); its freshness had no signal — this script is that signal.

Terminal states (exactly two green readings, everything else red):
- pin == index latest -> "pin CURRENT: <v>", exit 0
- pin < index latest  -> a ::warning:: naming the pin, the latest and the
  bump procedure, exit 0 — the pin advances deliberately per train, so
  staleness is a warning, never a failure (the registry drift job's
  CON-12 posture, benchweave-registry records.yml)
- pin > index latest  -> red: the pin names a release the index does not
  serve, so the [server] extra cannot install — that state is not fresh
  and must not read as fresh
- any inability to determine (pin shape, index shape, network after
  retries) -> red with the reason; a green run never means "unknown"

--index-url accepts a file:// URL so the warning and red arms replay a
saved index response (no live stale release exists to observe yet — the
design record's honest negative, §1.2).
"""

import argparse
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "benchweave-ui-html"
DEFAULT_INDEX = f"https://pypi.org/pypi/{PACKAGE}/json"
_REQ = re.compile(rf"^{PACKAGE}==(\d+\.\d+\.\d+)$")
_RETRIES = 3  # retries beyond the first attempt (design R2: reachability bound)
_TIMEOUT = 10  # seconds per fetch attempt


def _tuple(text: str) -> tuple[int, ...] | None:
    """Parse X.Y.Z into a comparable tuple; None when the shape is wrong."""
    if re.fullmatch(r"\d+\.\d+\.\d+", text) is None:
        return None
    return tuple(int(part) for part in text.split("."))


def _read_pin() -> tuple[str, tuple[int, ...]]:
    """Read the exact pin from pyproject [server] (the shape the test pins)."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = project["project"]["optional-dependencies"]["server"]
    reqs = [r for r in extras if r.startswith(PACKAGE)]
    if len(reqs) != 1:
        raise ValueError(
            f"expected exactly one {PACKAGE} requirement in [server], found {reqs!r}"
        )
    match = _REQ.fullmatch(reqs[0])
    if match is None:
        raise ValueError(
            f"the [server] {PACKAGE} pin is not an exact ==X.Y.Z specifier: "
            f"{reqs[0]!r} (tests/test_ui_html_pin.py is the shape gate)"
        )
    parsed = _tuple(match.group(1))
    assert parsed is not None  # the regex guarantees the shape here
    return match.group(1), parsed


def _fetch_latest(index_url: str) -> tuple[str, tuple[int, ...]]:
    """Fetch the index's latest version (network errors retried, never green)."""
    last_error: Exception | None = None
    body: bytes | None = None
    for _ in range(1 + _RETRIES):
        try:
            with urllib.request.urlopen(index_url, timeout=_TIMEOUT) as response:
                body = response.read()
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
    if body is None:
        raise RuntimeError(f"index unreachable after retries: {last_error}")
    try:
        payload = json.loads(body.decode("utf-8"))
        version = payload["info"]["version"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"index response is not a readable version payload: {exc}") from exc
    parsed = _tuple(version) if isinstance(version, str) else None
    if parsed is None:
        raise RuntimeError(f"index latest version is not X.Y.Z: {version!r}")
    return version, parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare the [server] extra's ui-html pin to the package index.",
    )
    parser.add_argument(
        "--index-url",
        default=DEFAULT_INDEX,
        help="index JSON URL (a file:// URL replays a saved response)",
    )
    args = parser.parse_args(argv)

    try:
        pin, pin_version = _read_pin()
    except (ValueError, KeyError) as exc:
        print(f"pin-freshness: cannot read the pin: {exc}", file=sys.stderr)
        return 1
    try:
        latest, latest_version = _fetch_latest(args.index_url)
    except RuntimeError as exc:
        print(f"pin-freshness: {exc}", file=sys.stderr)
        return 1

    if pin_version == latest_version:
        print(f"pin CURRENT: {pin}")
        return 0
    if pin_version < latest_version:
        print(
            f"::warning::{PACKAGE} pin {pin} is behind index latest {latest} — "
            "advance the exact pin in pyproject [server] on the next SDK train "
            "(gateway obligation 12 / PRD 12 Q5)"
        )
        return 0
    print(
        f"pin-freshness: pin {pin} is AHEAD of index latest {latest} — the pin "
        "names a release the index does not serve, so [server] cannot install",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
