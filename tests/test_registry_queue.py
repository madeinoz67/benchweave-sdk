"""Queue-stage derivation and the contributor status surface (CR-27/CR-31).

The queue's contract is the committed, hand-derived truth table
(``tests/fixtures/registry-clone/truth-table.json``, written before the
derivation code): every cell asserts both modes — full (PR state from the
fixture) and records-only (the loud ``stage_partial`` degradation).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry-clone"


@pytest.fixture()
def origin_key(tmp_path: Path) -> Path:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "origin.pem"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return key_path


def _run(*args: str) -> dict[str, Any]:
    from benchweave_sdk.cli import cli

    result = CliRunner().invoke(cli, ["registry", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _queue(clone: Path, *, pr_state: Path | None = None) -> dict[str, Any]:
    args = ["queue", "--registry-clone", str(clone)]
    if pr_state is not None:
        args += ["--pr-state", str(pr_state)]
    return _run(*args)


def _rows(report: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {
        (row["publisher"], row["plugin"], row["version"]): row
        for row in report["submissions"]
    }


def _truth_table() -> list[dict[str, Any]]:
    return json.loads((FIXTURE / "truth-table.json").read_bytes())["submissions"]


@pytest.fixture()
def clone(tmp_path: Path) -> Path:
    target = tmp_path / "registry-clone"
    shutil.copytree(FIXTURE, target)
    return target


def test_queue_full_mode_matches_the_committed_truth_table(clone: Path) -> None:
    report = _queue(clone, pr_state=FIXTURE / "pr-state.json")
    rows = _rows(report)
    for cell in _truth_table():
        row = rows[(cell["publisher"], cell["plugin"], cell["version"])]
        assert row["stage"] == cell["full"]["stage"], (cell, row)
        assert row["stage_partial"] is cell["full"]["stage_partial"], (cell, row)
    assert report["disclosures"] == []


def test_queue_records_only_matches_the_committed_truth_table(
    clone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("benchweave_sdk.registry_ops.gh_available", lambda: False)
    report = _queue(clone)
    rows = _rows(report)
    for cell in _truth_table():
        row = rows[(cell["publisher"], cell["plugin"], cell["version"])]
        assert row["stage"] == cell["records_only"]["stage"], (cell, row)
        assert row["stage_partial"] is cell["records_only"]["stage_partial"], (cell, row)
    # The degradation is loud: the disclosure names the under-derived stages.
    assert any(
        disclosure.startswith("stage_partial: pr_state_unavailable")
        for disclosure in report["disclosures"]
    )


def test_queue_rows_carry_evidence_naming_the_derivation_source(clone: Path) -> None:
    rows = _rows(_queue(clone, pr_state=FIXTURE / "pr-state.json"))
    assert rows[("northwind-instruments", "vmx3-power-supply", "1.0.0")][
        "evidence"
    ] == ["lifecycle:publish"]
    assert rows[("northwind-instruments", "osc-probe", "0.2.0")]["evidence"] == [
        "review:accepted",
        "pr:11:carries-manifest.sig",
    ]
    assert rows[("harborline-systems", "sig-analyzer", "0.3.0")]["evidence"] == [
        "pr:14:closed-unmerged"
    ]
    assert rows[("harborline-systems", "load-bank-ctl", "2.0.0")]["evidence"] == [
        "pr:12:review-activity"
    ]


def test_status_publisher_scoped_exact_sets(clone: Path) -> None:
    north = _run(
        "status", "--registry-clone", str(clone), "--publisher", "northwind-instruments"
    )
    harbor = _run(
        "status", "--registry-clone", str(clone), "--publisher", "harborline-systems"
    )
    def _keys(report: dict) -> set:
        return {(r["publisher"], r["plugin"], r["version"]) for r in report["submissions"]}

    north_keys = _keys(north)
    harbor_keys = _keys(harbor)
    assert north_keys == {
        ("northwind-instruments", "vmx3-power-supply", "1.0.0"),
        ("northwind-instruments", "vmx3-power-supply", "1.1.0"),
        ("northwind-instruments", "osc-probe", "0.1.0"),
        ("northwind-instruments", "osc-probe", "0.2.0"),
        ("northwind-instruments", "osc-probe", "0.3.0"),
    }
    assert harbor_keys == {
        ("harborline-systems", "load-bank-ctl", "1.4.0"),
        ("harborline-systems", "load-bank-ctl", "2.0.0"),
        ("harborline-systems", "sig-analyzer", "0.3.0"),
        ("harborline-systems", "sig-analyzer", "0.4.0"),
        ("harborline-systems", "sig-analyzer", "0.1.0"),
    }
    # Exact sets are disjoint across publishers (CR-31's exact-set arm).
    assert north_keys.isdisjoint(harbor_keys)
    # Records-only surface: the same loud partial disclosure as the queue.
    assert any(
        disclosure.startswith("stage_partial: pr_state_unavailable")
        for disclosure in north["disclosures"]
    )


def test_status_plugin_filter_narrows_within_a_publisher(clone: Path) -> None:
    report = _run(
        "status", "--registry-clone", str(clone),
        "--publisher", "northwind-instruments", "--plugin", "osc-probe",
    )
    assert {(row["plugin"], row["version"]) for row in report["submissions"]} == {
        ("osc-probe", "0.1.0"),
        ("osc-probe", "0.2.0"),
        ("osc-probe", "0.3.0"),
    }


def test_status_releases_carry_the_lifecycle_timeline_from_records(
    clone: Path,
) -> None:
    report = _run(
        "status", "--registry-clone", str(clone), "--publisher", "northwind-instruments"
    )
    timelines = {
        (row["plugin"], row["version"]): row["timeline"] for row in report["releases"]
    }
    assert timelines[("vmx3-power-supply", "1.0.0")] == [
        {
            "seq": 1,
            "op": "publish",
            "actor": "registry-maintainer",
            "created_at": "2026-09-28T00:00:00Z",
            "reason": "fixture: reviewed and admitted release (queue stage 1, published)",
        }
    ]
    assert timelines[("vmx3-power-supply", "1.1.0")] == [
        {
            "seq": 1,
            "op": "withdraw",
            "actor": "northwind-instruments",
            "created_at": "2026-09-28T00:00:00Z",
            "reason": "fixture: contributor withdrew before acceptance (queue stage 2, withdrawn)",
        }
    ]
    assert timelines[("osc-probe", "0.2.0")] == []


def test_status_unknown_publisher_is_an_exact_empty_set(clone: Path) -> None:
    report = _run(
        "status", "--registry-clone", str(clone), "--publisher", "acme-instruments"
    )
    assert report["submissions"] == []
    assert report["releases"] == []


# --- derivation arms beyond the committed table (inline mini-trees) ------------


def _mini_clone(
    tmp_path: Path,
    *,
    records: list[str] | None = None,
) -> Path:
    """A clone carrying only the named fixture record files (and their parents)."""
    clone = tmp_path / "mini"
    clone.mkdir()
    (clone / "records").mkdir()
    for rel in records or []:
        source = FIXTURE / rel
        target = clone / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, target)
    return clone


def _pr_fixture(tmp_path: Path, prs: list[dict[str, Any]]) -> Path:
    path = tmp_path / "pr-state.json"
    path.write_text(json.dumps({"prs": prs}))
    return path


def test_latest_review_outcome_wins_over_an_earlier_accepted(tmp_path: Path) -> None:
    """A stale accepted review cannot sign; the latest outcome governs (the
    design's stage 5 says *latest* review record — the only reading that keeps
    stage 5 reachable once a review history exists)."""
    clone = _mini_clone(
        tmp_path,
        records=[
            "records/submissions/northwind-instruments/osc-probe/0.1.0/artefacts/.gitkeep",
            "records/submissions/northwind-instruments/osc-probe/0.1.0/review-1.json",
        ],
    )
    # review-1 is accepted; add a later changes-requested review on top.
    first = json.loads(
        (clone / "records/submissions/northwind-instruments/osc-probe/0.1.0/review-1.json")
        .read_bytes()
    )
    second = dict(first)
    second["review"] = dict(first["review"], outcome="changes-requested")
    (
        clone / "records/submissions/northwind-instruments/osc-probe/0.1.0/review-2.json"
    ).write_text(json.dumps(second))
    pr = _pr_fixture(
        tmp_path,
        [{
            "number": 21,
            "state": "open",
            "head_ref": "submission/northwind-instruments-osc-probe-0.1.0",
            "files": [
                "records/submissions/northwind-instruments/osc-probe/0.1.0/artefacts/"
                "manifest.sig",
            ],
            "reviews": [],
        }],
    )
    rows = _rows(_queue(clone, pr_state=pr))
    assert rows[("northwind-instruments", "osc-probe", "0.1.0")]["stage"] == (
        "changes requested"
    )


def test_rejected_latest_review_maps_to_changes_requested(tmp_path: Path) -> None:
    """The seven-stage list carries no rejected stage; a rejected latest review
    means the submission was reviewed and not accepted — rendered as
    ``changes requested`` with the true outcome in the evidence."""
    clone = _mini_clone(
        tmp_path,
        records=[
            "records/submissions/northwind-instruments/osc-probe/0.1.0/artefacts/.gitkeep",
            "records/submissions/northwind-instruments/osc-probe/0.1.0/review-1.json",
        ],
    )
    record = json.loads(
        (clone / "records/submissions/northwind-instruments/osc-probe/0.1.0/review-1.json")
        .read_bytes()
    )
    record["review"] = dict(record["review"], outcome="rejected")
    (clone / "records/submissions/northwind-instruments/osc-probe/0.1.0/review-1.json").write_text(
        json.dumps(record)
    )
    rows = _rows(_queue(clone))
    row = rows[("northwind-instruments", "osc-probe", "0.1.0")]
    assert row["stage"] == "changes requested"
    assert "review:rejected" in row["evidence"]


def test_pr_only_submission_appears_in_full_mode_only(tmp_path: Path) -> None:
    """A submission whose records exist only inside an open PR is invisible to
    the records-only view and listed once PR state arrives."""
    clone = _mini_clone(tmp_path, records=[])
    pr = _pr_fixture(
        tmp_path,
        [{
            "number": 30,
            "state": "open",
            "head_ref": "submission/harborline-systems-sig-analyzer-0.9.0",
            "files": [
                "records/submissions/harborline-systems/sig-analyzer/0.9.0/artefacts/"
                "submission.json",
            ],
            "reviews": [],
        }],
    )
    rows = _rows(_queue(clone, pr_state=pr))
    assert rows[("harborline-systems", "sig-analyzer", "0.9.0")]["stage"] == "submitted"
    records_only = _rows(_queue(clone))
    assert ("harborline-systems", "sig-analyzer", "0.9.0") not in records_only


def test_publish_record_dominates_a_closed_pr(tmp_path: Path) -> None:
    """Precedence: a published release stays published even if its PR state
    says closed-unmerged (stage 1 outranks stage 2)."""
    clone = _mini_clone(
        tmp_path,
        records=[
            "records/lifecycle/northwind-instruments/vmx3-power-supply/1.0.0/1-publish.json",
            "records/submissions/northwind-instruments/vmx3-power-supply/1.0.0/artefacts/"
            ".gitkeep",
        ],
    )
    pr = _pr_fixture(
        tmp_path,
        [{
            "number": 40,
            "state": "closed",
            "head_ref": "submission/northwind-instruments-vmx3-power-supply-1.0.0",
            "files": [
                "records/submissions/northwind-instruments/vmx3-power-supply/1.0.0/"
                "artefacts/submission.json",
            ],
            "reviews": [],
        }],
    )
    rows = _rows(_queue(clone, pr_state=pr))
    assert rows[("northwind-instruments", "vmx3-power-supply", "1.0.0")]["stage"] == "published"


def test_merged_pr_without_records_discloses_partial(tmp_path: Path) -> None:
    """A merged PR whose records have not landed: the records ARE imminent, so
    the row discloses stage_partial rather than claiming records-final (fold
    row 3's honest-disclosure route)."""
    clone = _mini_clone(
        tmp_path,
        records=[
            "records/submissions/harborline-systems/sig-analyzer/0.3.0/artefacts/.gitkeep",
        ],
    )
    pr = _pr_fixture(
        tmp_path,
        [{
            "number": 70,
            "state": "merged",
            "head_ref": "submission/harborline-systems-sig-analyzer-0.3.0",
            "files": [
                "records/submissions/harborline-systems/sig-analyzer/0.3.0/artefacts/"
                "submission.json",
            ],
            "reviews": [],
        }],
    )
    rows = _rows(_queue(clone, pr_state=pr))
    row = rows[("harborline-systems", "sig-analyzer", "0.3.0")]
    assert row["stage"] == "submitted"
    assert row["stage_partial"] is True


def test_queue_rows_carry_lifecycle_and_unlist_markers(
    clone: Path, origin_key: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S10: the stage taxonomy stays the design's seven, but each queue row
    closes informationally — the served status lifecycle and the unlist
    record surface as markers beside the stage."""
    monkeypatch.setattr("benchweave_sdk.registry_ops.gh_available", lambda: False)
    from benchweave_sdk.cli import cli

    runner = CliRunner()
    for args in (
        ["publish-status", "northwind-instruments/vmx3-power-supply@1.0.0",
         "--origin-key", str(origin_key), "--expires-at", "2030-01-01T00:00:00Z"],
        ["yank", "northwind-instruments/vmx3-power-supply@1.0.0",
         "--origin-key", str(origin_key), "--reason", "r", "--actor", "a"],
        ["unlist", "northwind-instruments/vmx3-power-supply@1.0.0",
         "--reason", "r", "--actor", "a"],
    ):
        result = runner.invoke(cli, ["registry", *args, "--registry-clone", str(clone)])
        assert result.exit_code == 0, result.output
    rows = _rows(_queue(clone))
    row = rows[("northwind-instruments", "vmx3-power-supply", "1.0.0")]
    assert row["stage"] == "published"  # taxonomy unchanged
    assert row["lifecycle"] == "yanked"  # served-state marker
    assert row["unlisted"] is True  # record-driven marker
    # A row with neither marker carries explicit nulls, not absent keys.
    quiet = rows[("harborline-systems", "load-bank-ctl", "1.4.0")]
    assert quiet["lifecycle"] is None
    assert quiet["unlisted"] is False


def test_pr_without_a_resolvable_submission_key_is_disclosed(
    tmp_path: Path,
) -> None:
    """A PR whose carried files name no submission path and whose branch does
    not parse is reported in the disclosures, never silently dropped."""
    clone = _mini_clone(tmp_path, records=[])
    pr = _pr_fixture(
        tmp_path,
        [{
            "number": 50,
            "state": "open",
            "head_ref": "some-renamed-branch",
            "files": ["README.md"],
            "reviews": [],
        }],
    )
    report = _queue(clone, pr_state=pr)
    assert report["submissions"] == []
    assert any(
        disclosure.startswith("pr_unmapped:") for disclosure in report["disclosures"]
    )


def test_malformed_pr_state_fixture_refuses(tmp_path: Path) -> None:
    from benchweave_sdk.cli import cli

    bad = tmp_path / "bad.json"
    bad.write_text('{"nope": true}')
    result = CliRunner().invoke(
        cli,
        ["registry", "queue", "--registry-clone", str(tmp_path), "--pr-state", str(bad)],
    )
    assert result.exit_code == 1
    assert "pr_state_invalid:" in result.output
