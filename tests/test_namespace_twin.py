"""C5's SDK-side namespace twin: the committed similarity vectors, pinned.

The same five committed vectors in the registry repository's lane-rules.json
pin the namespace rule in BOTH repos (the twin-test discipline against drift
between the SDK's package-time check and the registry's vetting CI). The
committed copy under tests/fixtures/registry-clone/lane-rules.json is
byte-for-byte the registry repository's file at origin/main @ 21acea1
(sha256 0701d49aa2153265428182a0a0ea1ccfb810b39155246dde0c26d8663b00a262);
when a benchweave-registry checkout is available (BENCHWEAVE_REGISTRY_CLONE),
the copy is cross-checked against the live file so lane-rule drift surfaces
here too.

Two of the five vectors do not hold under the plain skeleton-plus-edit-distance
rule as implemented (skeleton distance 4 and 5 respectively, both beyond the
committed max of 2) and — because both comparators sit in the same
reserved_namespaces list with identically shaped candidates — no rule keyed
on lane-rules.json alone can satisfy both expectations at once. They are
pinned as strict xfails naming the defect: whichever side moves (rule or
data), this pin forces the reconciliation. Raised with the registry lane and
the coordinator on issue #225.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry-clone"
LANE_RULES = FIXTURE / "lane-rules.json"
#: Byte-for-byte source of the committed copy (disclosed in the module docstring).
LANE_RULES_SOURCE_DIGEST = (
    "0701d49aa2153265428182a0a0ea1ccfb810b39155246dde0c26d8663b00a262"
)

_VECTOR_DEFECT = (
    "committed-vector defect: skeleton distance exceeds the committed "
    "max_edit_distance=2, and no rule keyed on lane-rules.json alone can "
    "satisfy this vector together with the other reserved-list vector — "
    "the rule or the data must move registry-side (issue #225)"
)


def _vectors() -> list[dict[str, str]]:
    payload = json.loads(LANE_RULES.read_bytes())
    return payload["similarity_rule"]["vectors"]


def _classify(candidate: str, existing: str) -> str:
    from benchweave_sdk.publishing import check_namespace

    rules = _rules()
    findings = check_namespace(f"{candidate}/pkg", rules, {existing}, {})
    if any(f.startswith("namespace_reserved:") for f in findings):
        return "reserved"
    if any(f.startswith("namespace_lookalike:") for f in findings):
        return "lookalike"
    return "distinct"


def _rules() -> Any:
    from benchweave_sdk.publishing import LaneRules

    return LaneRules.load(FIXTURE)


def test_the_committed_copy_is_the_registry_repository_s_bytes() -> None:
    digest = hashlib.sha256(LANE_RULES.read_bytes()).hexdigest()
    assert digest == LANE_RULES_SOURCE_DIGEST


def _distance_beyond_committed_max(vector: dict[str, str]) -> bool:
    """True when the vector's skeletons sit beyond max_edit_distance."""
    from benchweave_sdk.publishing import LaneRules, _edit_distance, _skeleton

    rules = LaneRules.load(FIXTURE)
    distance = _edit_distance(
        _skeleton(vector["candidate"], rules), _skeleton(vector["existing"], rules)
    )
    return distance > rules.similarity_max_distance


def _vector_params() -> list[Any]:
    """Vectors whose skeletons sit beyond the committed max carry the xfail.

    Only where the expectation is lookalike or reserved — a beyond-max
    distance with a distinct expectation is exactly what the rule says.
    Strict: a rule change that satisfies one of these pins turns its xfail
    into an XPASS failure, forcing the reconciliation to be deliberate.
    """
    return [
        pytest.param(
            vector,
            marks=pytest.mark.xfail(strict=True, reason=_VECTOR_DEFECT),
        )
        if _distance_beyond_committed_max(vector) and vector["expected"] != "distinct"
        else pytest.param(vector)
        for vector in json.loads(LANE_RULES.read_bytes())["similarity_rule"]["vectors"]
    ]


@pytest.mark.parametrize("vector", _vector_params())
def test_committed_vectors_pin_the_sdk_rule(vector: dict[str, str]) -> None:
    assert _classify(vector["candidate"], vector["existing"]) == vector["expected"]


def test_live_registry_clone_matches_the_committed_copy(
    tmp_path: Path,
) -> None:
    """Cross-check against a live registry checkout when one is provided.

    Skipped unless BENCHWEAVE_REGISTRY_CLONE names a checkout — CI has none;
    locally the drift guard forces this copy to be refreshed deliberately
    whenever the registry repository moves its lane rules.
    """
    live = os.environ.get("BENCHWEAVE_REGISTRY_CLONE")
    if not live:
        pytest.skip("BENCHWEAVE_REGISTRY_CLONE not set; no live registry checkout")
    live_file = Path(live) / "lane-rules.json"
    assert live_file.is_file(), f"BENCHWEAVE_REGISTRY_CLONE has no lane-rules.json: {live}"
    live_digest = hashlib.sha256(live_file.read_bytes()).hexdigest()
    assert live_digest == LANE_RULES_SOURCE_DIGEST, (
        "the registry repository's lane-rules.json moved; refresh the committed "
        "copy under tests/fixtures/registry-clone/ deliberately (the twin reads "
        "its vectors from it)"
    )


# --- the package-time trio at CLI level (C5's SDK-side re-pin) ---------------------


def _make_plugin(root: Path, name: str) -> Path:
    plugin = root / name
    source = plugin / "src" / f"benchweave_{name}"
    source.mkdir(parents=True)
    descriptor = {
        "descriptor_version": "1.0",
        "id": name,
        "display_name": name,
        "description": f"fixture plugin {name}",
        "otdp_version": "0.1.0",
        "identity": {"strategy": "adapter", "manufacturer": "Exampleworks",
                     "model": "widget-1", "firmware_policy": "commissioned"},
        "integration": {
            "mode": "adapter",
            "adapter": {
                "entry_point": f"benchweave_{name}.adapter:create_plugin",
                "api_version": "1.1", "version": "0.1.0",
                "dependencies": [], "permissions": [],
            },
        },
        "transport": {"type": "serial", "connection_key": "widget"},
        "capabilities": ["identify", "read"],
    }
    (source / "descriptor.json").write_text(json.dumps(descriptor, indent=2))
    (source / "adapter.py").write_text("def create_plugin():\n    return object()\n")
    (source / "__init__.py").write_text("")
    (plugin / "docs").mkdir()
    (plugin / "docs" / "protocol-evidence.md").write_text("# Evidence\n\nSynthetic only.\n")
    (plugin / "LICENSE").write_text("MIT (fixture)\n")
    (plugin / "README.md").write_text("# Fixture\n")
    (plugin / "pyproject.toml").write_text(
        '[project]\nname = "widget"\nversion = "0.1.0"\nrequires-python = ">=3.13"\n'
    )
    return plugin


def _package(clone: Path, tmp_path: Path, publisher: str, plugin: str) -> Any:
    from benchweave_sdk.cli import cli

    plugin_dir = _make_plugin(tmp_path, plugin.replace("-", "_"))
    out = tmp_path / "out" / f"{publisher}-{plugin}"
    return CliRunner().invoke(
        cli,
        [
            "package", str(plugin_dir),
            "--registry-clone", str(clone),
            "--source-url", "https://example.invalid/src",
            "--revision", "1" * 40,
            "--publisher", publisher,
            "--plugin", plugin,
            "--out", str(out),
            "--capability", "none",
        ],
    )


def test_cli_package_refuses_a_reserved_namespace(tmp_path: Path) -> None:
    result = _package(FIXTURE, tmp_path, "otdp", "probe-ctl")
    assert result.exit_code == 1, result.output
    assert "namespace_reserved:otdp" in result.output


def test_cli_package_refuses_a_cross_owner_collision(tmp_path: Path) -> None:
    """The exact id claimed by a different RECORDED owner collides.

    The owner ruling (issue #223 fold) lets two authors register the same
    plugin NAME under their own namespaces — so the collision arm needs a
    release tree whose recorded owner differs from the packager, which is
    the transferred/mis-recorded shape the gate exists for.
    """
    clone = tmp_path / "registry-clone"
    shutil.copytree(FIXTURE, clone)
    manifest_path = (
        clone / "releases" / "benchweave-registry" / "northwind-instruments"
        / "vmx3-power-supply" / "1.0.0" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_bytes())
    manifest["publisher_id"] = "harborline-systems"
    manifest_path.write_text(json.dumps(manifest))
    result = _package(clone, tmp_path, "northwind-instruments", "vmx3-power-supply")
    assert result.exit_code == 1, result.output
    assert "namespace_collision:northwind-instruments/vmx3-power-supply" in result.output


def test_cli_package_flags_a_lookalike_without_refusing(tmp_path: Path) -> None:
    result = _package(FIXTURE, tmp_path, "harborline-systemz", "probe-ctl")
    assert result.exit_code == 0, result.output
    assert "namespace_lookalike" in result.output
    # The flag rides the draft too, for the reviewer's eyes.
    submission = json.loads(
        (tmp_path / "out" / "harborline-systemz-probe-ctl" / "submission.json").read_bytes()
    )
    assert any("harborline-systemz~harborline-systems" in flag
               for flag in submission["namespace_lookalikes"])
