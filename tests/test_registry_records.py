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
    )
    assert "withdraw_after_publication:" in output
    # And nothing was written.
    assert not (
        clone / "records" / "lifecycle" / "northwind-instruments"
        / "vmx3-power-supply" / "1.0.0" / "2-withdraw.json"
    ).exists()


def test_transfer_appends_the_record_with_both_consents(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    _ok(
        clone, "transfer", PUBLISHED,
        "--to", "harborline-systems",
        "--consent-from", "northwind-instruments consents per owners-meeting note 7",
        "--consent-to", "harborline-systems accepts per owners-meeting note 7",
        "--vetting-ref", "publishers.json harborline-systems entry + V-rows V-01..V-06",
        "--reason", "maintenance transfer to the maintainer's org",
        "--actor", "registry-coordinator",
    )
    record = _record(clone, PUBLISHED, "2-transfer.json")
    assert record["lifecycle"]["op"] == "transfer"
    assert record["lifecycle"]["transfer"] == {
        "from_publisher": "northwind-instruments",
        "to_publisher": "harborline-systems",
        "consents": [
            "northwind-instruments consents per owners-meeting note 7",
            "harborline-systems accepts per owners-meeting note 7",
        ],
        "vetting_reference": "publishers.json harborline-systems entry + V-rows V-01..V-06",
    }
    assert record["actor"] == "registry-coordinator"


def test_transfer_refuses_consents_that_do_not_name_the_parties(
    tmp_path: Path,
) -> None:
    clone = _clone(tmp_path)
    output = _refuse(
        clone, "transfer", PUBLISHED,
        "--to", "harborline-systems",
        "--consent-from", "someone else entirely",
        "--consent-to", "harborline-systems accepts",
        "--vetting-ref", "v",
        "--reason", "r", "--actor", "a",
    )
    assert "transfer_invalid:" in output
    output = _refuse(
        clone, "transfer", PUBLISHED,
        "--to", "harborline-systems",
        "--consent-from", "northwind-instruments consents",
        "--consent-to", "a third party accepts",
        "--vetting-ref", "v",
        "--reason", "r", "--actor", "a",
    )
    assert "transfer_invalid:" in output


def test_transfer_refuses_a_self_transfer(tmp_path: Path) -> None:
    clone = _clone(tmp_path)
    output = _refuse(
        clone, "transfer", PUBLISHED,
        "--to", "northwind-instruments",
        "--consent-from", "northwind-instruments consents",
        "--consent-to", "northwind-instruments accepts",
        "--vetting-ref", "v",
        "--reason", "r", "--actor", "a",
    )
    assert "transfer_invalid:" in output
