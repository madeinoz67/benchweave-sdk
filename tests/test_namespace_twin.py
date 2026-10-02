"""C5's SDK-side namespace twin: the committed similarity vectors, pinned.

The classifier is NOT flat: the seven committed vectors in the registry
repository's lane-rules.json are satisfiable only by a TWO-COMPARISON-SET
rule (the registry lane's landed resolution, issue #225): near a RESERVED
name the verdict is ``reserved``; near a VETTED namespace it is
``lookalike``. Near = skeleton equality, skeleton-prefix containment, or
edit distance within the committed max. Each vector's expected label TYPES
its comparison set — sim-v3 runs reserved (``otdp-tools`` extends the
reserved ``otdp``); the others run vetted (``benchweave`` and
``madeinoz67`` playing abstract incumbent vetted namespaces); sim-v6 pins
skeleton equality itself (``b3nchweave`` confusable-folds onto
``benchweave``) and expects the ``same`` verdict.

The typed rows below are replicated verbatim from the registry lane's
committed truth table (benchweave-registry origin/feat/issue225-registry-mgmt
@ e913e92, first committed 114f3b1: tests/fixtures/issue225/
namespace-vetting.truth-table.json, rows sim-v1..sim-v7) and are
cross-checked against this repo's committed lane-rules.json copy so neither
side can drift alone. When a benchweave-registry checkout is available
(BENCHWEAVE_REGISTRY_CLONE — it must carry the registry lane's branch state
until that branch merges; main's lane-rules.json differs by design), the
copy is also cross-checked against the live file.

Gate posture stays surface-local (the twins pin the CLASSIFIER): at SDK
package time a lookalike is flagged-not-refused and rides the draft; at
registry vetting admission it refuses (the registry lane's ns-03 row).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry-clone"
LANE_RULES = FIXTURE / "lane-rules.json"
#: Byte-for-byte source of the committed copy: the registry lane's fold
#: bytes (e913e92) — the cross-branch contract is byte-identical
#: lane-rules.json on both branches.
LANE_RULES_SOURCE_DIGEST = (
    "1761d91a874991575e45cb0b09d811bfdb7ffd30b6d29525599a76dbd86bc842"
)

#: The typed vector rows, verbatim from the registry lane's committed truth
#: table (path and commit in the module docstring). comparison_set types the
#: set each vector exercises; expected is the classifier verdict.
TYPED_VECTORS: tuple[dict[str, str], ...] = (
    {"id": "sim-v1", "candidate": "benchweave-labs", "existing": "benchweave",
     "expected": "lookalike", "comparison_set": "vetted"},
    {"id": "sim-v2", "candidate": "benchwave", "existing": "benchweave",
     "expected": "lookalike", "comparison_set": "vetted"},
    {"id": "sim-v3", "candidate": "otdp-tools", "existing": "otdp",
     "expected": "reserved", "comparison_set": "reserved"},
    {"id": "sim-v4", "candidate": "madeinoz68", "existing": "madeinoz67",
     "expected": "lookalike", "comparison_set": "vetted"},
    {"id": "sim-v5", "candidate": "acme-power", "existing": "madeinoz67",
     "expected": "distinct", "comparison_set": "vetted"},
    {"id": "sim-v6", "candidate": "b3nchweave", "existing": "benchweave",
     "expected": "same", "comparison_set": "vetted"},
    {"id": "sim-v7", "candidate": "madeinoz67-labs", "existing": "madeinoz67",
     "expected": "lookalike", "comparison_set": "vetted"},
)


def _rules() -> Any:
    from benchweave_sdk.publishing import LaneRules

    return LaneRules.load(FIXTURE)


def _lane_vectors() -> list[dict[str, str]]:
    return json.loads(LANE_RULES.read_bytes())["similarity_rule"]["vectors"]


def test_the_committed_copy_is_the_registry_repository_s_bytes() -> None:
    digest = hashlib.sha256(LANE_RULES.read_bytes()).hexdigest()
    assert digest == LANE_RULES_SOURCE_DIGEST


def test_the_typed_rows_agree_with_the_committed_lane_vectors() -> None:
    """Neither side drifts alone: every typed row's candidate/existing/
    expected equals the committed lane-rules.json vector with the same
    (candidate, existing) pair."""
    by_pair = {
        (vector["candidate"], vector["existing"]): vector for vector in _lane_vectors()
    }
    assert len(by_pair) == len(TYPED_VECTORS)
    for row in TYPED_VECTORS:
        vector = by_pair[(row["candidate"], row["existing"])]
        assert vector["expected"] == row["expected"], row


@pytest.mark.parametrize("row", TYPED_VECTORS, ids=[r["id"] for r in TYPED_VECTORS])
def test_committed_vectors_pin_the_typed_classifier(row: dict[str, str]) -> None:
    from benchweave_sdk.publishing import namespace_verdict

    verdict = namespace_verdict(
        row["candidate"],
        row["existing"],
        rules=_rules(),
        reserved=row["comparison_set"] == "reserved",
    )
    assert verdict == row["expected"], row


def test_skeleton_equal_namespaces_verdict_same() -> None:
    """The strongest impersonation shape — a confusable-folded skeleton
    EXACTLY equal to an existing namespace — is not 'distinct'."""
    from benchweave_sdk.publishing import namespace_verdict

    assert namespace_verdict(
        "n0rthwind-instruments", "northwind-instruments",
        rules=_rules(), reserved=False,
    ) == "same"


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


def test_cli_package_refuses_a_reserved_namespace_exact(tmp_path: Path) -> None:
    result = _package(FIXTURE, tmp_path, "otdp", "probe-ctl")
    assert result.exit_code == 1, result.output
    assert "namespace_reserved:otdp" in result.output


def test_cli_package_refuses_an_extension_of_a_reserved_namespace(tmp_path: Path) -> None:
    """The classifier's near-aware reserved arm at package time: sim-v3's
    gate semantics — 'otdp-tools' extends the reserved 'otdp' and refuses,
    never merely flags."""
    result = _package(FIXTURE, tmp_path, "otdp-tools", "probe-ctl")
    assert result.exit_code == 1, result.output
    assert "namespace_reserved:otdp-tools" in result.output


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


def test_cli_package_flags_a_containment_lookalike(tmp_path: Path) -> None:
    """sim-v1's gate semantics: an extension of a vetted namespace
    ('harborline-systems-labs' extends 'harborline-systems') flags for
    review, never refuses."""
    result = _package(FIXTURE, tmp_path, "harborline-systems-labs", "probe-ctl")
    assert result.exit_code == 0, result.output
    assert "namespace_lookalike" in result.output


def test_cli_package_flags_a_skeleton_equal_namespace(tmp_path: Path) -> None:
    """The d=0 shape ('n0rthwind-instruments' confusable-folds exactly onto
    the vetted 'northwind-instruments') flags — the pre-typed rule passed
    it silently; the typed classifier's near rule covers equality."""
    result = _package(FIXTURE, tmp_path, "n0rthwind-instruments", "probe-ctl")
    assert result.exit_code == 0, result.output
    assert "namespace_lookalike" in result.output


# --- fold-supplement arms: the delimiter-boundary ruling and the plugin arm ---


def test_cli_package_refuses_a_reserved_extension_at_a_separator_boundary(
    tmp_path: Path,
) -> None:
    """S1: 'dev-tools-inc' extends reserved 'dev' at a real separator
    boundary — refuses as reserved."""
    result = _package(FIXTURE, tmp_path, "dev-tools-inc", "probe-ctl")
    assert result.exit_code == 1, result.output
    assert "namespace_reserved:dev-tools-inc" in result.output


def test_cli_package_passes_a_reserved_prefixed_name_without_the_boundary(
    tmp_path: Path,
) -> None:
    """S1's control: 'devlin-instruments' shares reserved dev's prefix with
    NO separator boundary — skeleton-prefix alone is not containment; it
    falls to the vetted comparison (distinct against this fixture's
    namespaces) and packages cleanly."""
    result = _package(FIXTURE, tmp_path, "devlin-instruments", "probe-ctl")
    assert result.exit_code == 0, result.output
    assert "namespace_reserved" not in result.output


def test_cli_package_refuses_a_confusable_reserved_plugin(tmp_path: Path) -> None:
    """S3: '5im-psu' confusable-folds (5->s) exactly onto reserved
    'sim-psu' — the plugin segment's near arm refuses, not just the exact
    name."""
    result = _package(FIXTURE, tmp_path, "harborline-systems", "5im-psu")
    assert result.exit_code == 1, result.output
    assert "namespace_reserved:5im-psu" in result.output


def test_cli_package_refuses_a_reserved_plugin_extension(tmp_path: Path) -> None:
    """S3: 'sim-psu-labs' extends reserved 'sim-psu' at a separator
    boundary — refuses."""
    result = _package(FIXTURE, tmp_path, "harborline-systems", "sim-psu-labs")
    assert result.exit_code == 1, result.output
    assert "namespace_reserved:sim-psu-labs" in result.output


def test_classifier_boundary_and_params_parity() -> None:
    """S1 at the classifier, plus S4's param-consumption parity: a
    params-moved rules file (extra separator '+', case_sensitive flipped)
    yields IDENTICAL verdicts on the SDK and registry classifiers — the
    digest pin can never catch this drift class. Runs the registry
    classifier from a checkout named by BENCHWEAVE_REGISTRY_CLONE when
    present; otherwise asserts the SDK verdicts alone (CI has no checkout).
    """
    from benchweave_sdk.publishing import LaneRules, namespace_verdict

    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "rules-clone"
        clone.mkdir()
        rules_doc = json.loads(LANE_RULES.read_bytes())
        params = rules_doc["similarity_rule"]["params"]
        params["separator_characters"] = [*params["separator_characters"], "+"]
        params["case_sensitive"] = True
        (clone / "lane-rules.json").write_text(json.dumps(rules_doc))
        rules = LaneRules.load(clone)

        cases = [
            # (candidate, existing, reserved, expected) under the moved params
            ("otdp+tools", "otdp", True, "reserved"),   # '+' folds + boundary
            ("Benchweave-Labs", "benchweave", False, "lookalike"),  # both casefold
            ("devlin-instruments", "dev", True, "distinct"),  # no boundary
            ("dev-tools-inc", "dev", True, "reserved"),
            ("sim-psu-labs", "sim-psu", True, "reserved"),
            ("5im-psu", "sim-psu", True, "same"),
        ]
        for candidate, existing, reserved, expected in cases:
            assert namespace_verdict(candidate, existing, rules, reserved=reserved) == expected, (
                candidate
            )

        registry_clone = os.environ.get("BENCHWEAVE_REGISTRY_CLONE")
        if not registry_clone:
            pytest.skip("BENCHWEAVE_REGISTRY_CLONE not set; SDK-side parity only")

        scripts = Path(registry_clone) / "scripts"
        sys.path.insert(0, str(scripts))
        try:
            import validate_records as reg

            # One case is excluded until the registry lane's wave-2 lands the
            # delimiter-boundary ruling: devlin-instruments vs dev — their
            # LANDED classifier still plain-prefixes skeletons (verdict
            # 'reserved'); the ruling (and this SDK classifier) say 'distinct'.
            # The exclusion lifts in the same wave as the held vector re-sync.
            pending_boundary = {"devlin-instruments"}
            for candidate, existing, reserved, expected in cases:
                if candidate in pending_boundary:
                    continue
                theirs = reg.namespace_verdict(
                    candidate, existing, reserved=reserved, rules=rules_doc
                )
                ours = namespace_verdict(candidate, existing, rules, reserved=reserved)
                assert ours == theirs == expected, (candidate, ours, theirs)
        finally:
            sys.path.remove(str(scripts))
            sys.modules.pop("validate_records", None)
