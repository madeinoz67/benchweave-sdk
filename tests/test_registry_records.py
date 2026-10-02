"""The record-only lifecycle commands: unlist, withdraw, transfer (CR-17/32).

None of the three takes a key: each appends exactly one lifecycle record and
touches no status document. Withdraw is pre-acceptance only; unlist keeps the
release admissible (the catalogue row drops registry-side); transfer carries
both consents and the receiver vetting reference.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from click.testing import CliRunner

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry-clone"
PUBLISHED = "northwind-instruments/vmx3-power-supply@1.0.0"  # has a publish record
PRE_ACCEPTANCE = "harborline-systems/sig-analyzer@0.3.0"  # submission only


def _clone(tmp_path: Path) -> Path:
    target = tmp_path / "registry-clone"
    shutil.copytree(FIXTURE, target)
    return target


def _invoke(clone: Path, *args: str) -> Any:
    from benchweave_sdk.cli import cli

    return CliRunner().invoke(cli, ["registry", *args, "--registry-clone", str(clone)])


def _ok(clone: Path, *args: str) -> Any:
    result = _invoke(clone, *args)
    assert result.exit_code == 0, result.output
    return result


def _refuse(clone: Path, *args: str) -> str:
    result = _invoke(clone, *args)
    assert result.exit_code == 1, result.output
    return result.output


def _record(clone: Path, ref: str, name: str) -> dict[str, Any]:
    publisher, rest = ref.split("/", 1)
    plugin, version = rest.split("@")
    path = (
        clone / "records" / "lifecycle" / publisher / plugin / version / name
    )
    return json.loads(path.read_bytes())


def test_unlist_appends_only_the_record(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    _ok(clone, "unlist", PUBLISHED, "--reason", "superseded", "--actor", "registry-maintainer")
    record = _record(clone, PUBLISHED, "2-unlist.json")
    assert record["record_type"] == "lifecycle"
    assert record["record_version"] == "1.1.0"
    assert record["lifecycle"]["op"] == "unlist"
    assert record["lifecycle"]["reason"] == "superseded"
    assert record["actor"] == "registry-maintainer"
    # No status document appears: the release stays resolvable and admissible
    # (CR-32/E4); the catalogue row drops at index regeneration, registry-side.
    status = (
        clone / "releases" / "benchweave-registry" / "northwind-instruments"
        / "vmx3-power-supply" / "1.0.0" / "status.json"
    )
    assert not status.exists()
    # The publish record is untouched beside the new file.
    assert _record(clone, PUBLISHED, "1-publish.json")["lifecycle"]["op"] == "publish"


def test_withdraw_works_pre_acceptance_and_flips_the_queue(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    _ok(
        clone, "withdraw", PRE_ACCEPTANCE,
        "--reason", "superseded by a reworked submission", "--actor", "harborline-systems",
        "--kind", "community-shared",
    )
    record = _record(clone, PRE_ACCEPTANCE, "1-withdraw.json")
    assert record["lifecycle"]["op"] == "withdraw"
    assert record["actor"] == "harborline-systems"
    # The queue's records-only view derives withdrawn from the new record.
    from benchweave_sdk.registry_ops import load_records_view, parse_release_ref

    view = load_records_view(clone)
    key = parse_release_ref(PRE_ACCEPTANCE)
    assert view.ops(key) == frozenset({"withdraw"})


def test_withdraw_after_publication_refuses(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    output = _refuse(
        clone, "withdraw", PUBLISHED, "--reason", "too late", "--actor", "whoever",
        "--kind", "community-shared",
    )
    assert "withdraw_after_publication:" in output
    # And nothing was written.
    assert not (
        clone / "records" / "lifecycle" / "northwind-instruments"
        / "vmx3-power-supply" / "1.0.0" / "2-withdraw.json"
    ).exists()


def test_withdraw_requires_an_explicit_kind(tmp_path: Path) -> None:
    """Pre-acceptance withdrawal has no honest default kind — the CR-56 tag is
    the record's class and must be chosen, not defaulted (fold row 4)."""
    clone = _clone(tmp_path)
    output = _refuse(
        clone, "withdraw", PRE_ACCEPTANCE, "--reason", "r", "--actor", "a",
    )
    assert "record_kind_required:" in output
    assert not (
        clone / "records" / "lifecycle" / "harborline-systems"
        / "sig-analyzer" / "0.3.0"
    ).exists()


def test_transfer_appends_the_record_with_both_publisher_ids(tmp_path: Path) -> None:
    """Consents carry the exact publisher ids (the registry gate's landed
    semantics — its check is `needed <= set(consents)`), with optional
    evidence text riding after them; the vetting reference is the canonical
    publishers.json#<receiver> citation."""
    clone = _clone(tmp_path)
    _ok(
        clone, "transfer", PUBLISHED,
        "--to", "harborline-systems",
        "--consent-from", "northwind-instruments consents per owners-meeting note 7",
        "--consent-to", "harborline-systems accepts per owners-meeting note 7",
        "--reason", "maintenance transfer to the maintainer's org",
        "--actor", "registry-coordinator",
    )
    record = _record(clone, PUBLISHED, "2-transfer.json")
    assert record["lifecycle"]["op"] == "transfer"
    assert record["lifecycle"]["transfer"] == {
        "from_publisher": "northwind-instruments",
        "to_publisher": "harborline-systems",
        "consents": [
            "northwind-instruments",
            "harborline-systems",
            "northwind-instruments consents per owners-meeting note 7",
            "harborline-systems accepts per owners-meeting note 7",
        ],
        "vetting_reference": "publishers.json#harborline-systems",
    }
    assert record["actor"] == "registry-coordinator"


def test_transfer_defaults_the_canonical_vetting_citation(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    _ok(
        clone, "transfer", PUBLISHED,
        "--to", "harborline-systems",
        "--reason", "r", "--actor", "a",
    )
    transfer = _record(clone, PUBLISHED, "2-transfer.json")["lifecycle"]["transfer"]
    assert transfer["consents"] == ["northwind-instruments", "harborline-systems"]
    assert transfer["vetting_reference"] == "publishers.json#harborline-systems"


def test_transfer_refuses_a_noncanonical_vetting_reference(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    output = _refuse(
        clone, "transfer", PUBLISHED,
        "--to", "harborline-systems",
        "--vetting-ref", "publishers.json harborline-systems entry + V-rows V-01..V-06",
        "--reason", "r", "--actor", "a",
    )
    assert "transfer_vetting_unresolved:" in output
    assert "publishers.json#harborline-systems" in output


def test_transfer_refuses_an_unvetted_receiver(tmp_path: Path) -> None:
    """Transfer is re-vetting: a receiver without a publishers.json vetting
    block refuses with the registry gate's standing prefix."""
    clone = _clone(tmp_path)
    pub_path = clone / "records" / "publishers.json"
    pub = json.loads(pub_path.read_bytes())
    for entry in pub["publishers"]:
        if entry["publisher_id"] == "harborline-systems":
            entry.pop("vetting", None)
    pub_path.write_text(json.dumps(pub))
    output = _refuse(
        clone, "transfer", PUBLISHED,
        "--to", "harborline-systems",
        "--reason", "r", "--actor", "a",
    )
    assert "transfer_receiver_unvetted:harborline-systems" in output
    output = _refuse(
        clone, "transfer", PUBLISHED,
        "--to", "acme-instruments",
        "--reason", "r", "--actor", "a",
    )
    assert "transfer_receiver_unvetted:acme-instruments" in output


def test_transfer_refuses_a_malformed_receiver_vetting_block(tmp_path: Path) -> None:
    """S8: key-presence is too weak — an entry whose vetting block is
    schema-INVALID (a required key missing) must refuse at the CLI with the
    same prefix the registry's records CI emits, not pass here and refuse
    there."""
    clone = _clone(tmp_path)
    pub_path = clone / "records" / "publishers.json"
    pub = json.loads(pub_path.read_bytes())
    for entry in pub["publishers"]:
        if entry["publisher_id"] == "harborline-systems":
            entry["vetting"].pop("cited_rows")
    pub_path.write_text(json.dumps(pub))
    output = _refuse(
        clone, "transfer", PUBLISHED,
        "--to", "harborline-systems",
        "--reason", "r", "--actor", "a",
    )
    assert "transfer_receiver_unvetted:harborline-systems" in output


# --- supplement rows: existence checks (S11) ---------------------------------------


def test_withdraw_refuses_when_the_submission_is_absent(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    output = _refuse(
        clone, "withdraw", "northwind-instruments/ghost-plugin@1.0.0",
        "--reason", "r", "--actor", "a", "--kind", "community-shared",
    )
    assert "record_subject_absent:" in output


def test_unlist_refuses_when_the_release_is_absent(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    output = _refuse(
        clone, "unlist", "harborline-systems/sig-analyzer@0.3.0",
        "--reason", "r", "--actor", "a",
    )
    assert "record_subject_absent:" in output


def test_transfer_refuses_when_the_release_is_absent(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    output = _refuse(
        clone, "transfer", "harborline-systems/sig-analyzer@0.3.0",
        "--to", "northwind-instruments",
        "--reason", "r", "--actor", "a",
    )
    assert "record_subject_absent:" in output


def test_transfer_refuses_a_self_transfer(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    output = _refuse(
        clone, "transfer", PUBLISHED,
        "--to", "northwind-instruments",
        "--reason", "r", "--actor", "a",
    )
    assert "transfer_invalid:" in output
