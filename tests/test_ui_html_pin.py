"""The renderer pin discipline (PRD 12 Q5, gateway obligation 12).

The [server] extra pins benchweave-ui-html EXACTLY. A range would let
resolution drift the host's renderer bytes between installs — re-opening
the silent drift the exact pin exists to close (I1-D5's closure, the
#309 record §4.6). This test refuses the range shape and the removal.
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_REQ = re.compile(r"^benchweave-ui-html==(\d+\.\d+\.\d+)$")


def test_server_extra_pins_benchweave_ui_html_exactly() -> None:
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["optional-dependencies"]["server"]
    pins = [r for r in extras if r.startswith("benchweave-ui-html")]
    assert len(pins) == 1, pins  # present, not duplicated
    assert _REQ.fullmatch(pins[0]), pins[0]  # ==X.Y.Z, one specifier, no range
