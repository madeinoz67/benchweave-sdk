"""The status-document discipline and its keyed commands (CR-12/CR-28/CR-29).

publish-status writes the baseline pair; yank and advise rewrite under
sequence+1 and re-sign; every record write is an append-only new file. Keys
are runtime Ed25519 keypairs generated in-test — the key never enters any
repository or CI (CR-12).
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "registry-clone"
SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "src" / "benchweave_sdk" / "standards" / "registry" / "0.1.1"
    / "release-status.schema.json"
)
RELEASE = "northwind-instruments/vmx3-power-supply@1.0.0"


@pytest.fixture()
def clone(tmp_path: Path) -> Path:
    target = tmp_path / "registry-clone"
    shutil.copytree(FIXTURE, target)
    return target


@pytest.fixture()
def origin_key(tmp_path: Path) -> tuple[Path, Any]:
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
    return key_path, key.public_key()


def _invoke(clone: Path, *args: str) -> Any:
    from benchweave_sdk.cli import cli

    result = CliRunner().invoke(cli, ["registry", *args, "--registry-clone", str(clone)])
    return result


def _ok(clone: Path, *args: str) -> Any:
    result = _invoke(clone, *args)
    assert result.exit_code == 0, result.output
    return result


def _refuse(clone: Path, *args: str) -> str:
    result = _invoke(clone, *args)
    assert result.exit_code == 1, result.output
    return result.output


def _status_path(clone: Path) -> Path:
    return (
        clone / "releases" / "benchweave-registry" / "northwind-instruments"
        / "vmx3-power-supply" / "1.0.0" / "status.json"
    )


def _read_status(clone: Path) -> dict[str, Any]:
    return json.loads(_status_path(clone).read_bytes())


def _validate_schema(doc: dict[str, Any]) -> None:
    import jsonschema

    jsonschema.validate(doc, json.loads(SCHEMA.read_bytes()))


def _signature_verifies(clone: Path, public: Any) -> None:
    from cryptography.exceptions import InvalidSignature

    release_dir = _status_path(clone).parent
    signature = (release_dir / "status.sig").read_bytes()
    try:
        public.verify(signature, _status_path(clone).read_bytes())
    except InvalidSignature as exc:
        pytest.fail(f"status.sig does not verify over the status bytes: {exc}")


# --- publish-status (the section 1.2 fix, durable) --------------------------------


def test_publish_status_writes_a_schema_valid_baseline_pair(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, public = origin_key
    result = _ok(
        clone, "publish-status", RELEASE, "--origin-key", str(key_path),
        "--expires-at", "2030-01-01T00:00:00Z",
    )
    doc = _read_status(clone)
    _validate_schema(doc)
    assert doc["sequence"] == 1
    assert doc["lifecycle"] == "published"
    assert doc["release"] == {
        "registry_id": "benchweave-registry",
        "package_id": "northwind-instruments/vmx3-power-supply",
        "version": "1.0.0",
        "manifest_sha256": __import__("hashlib").sha256(
            (
                clone / "releases" / "benchweave-registry" / "northwind-instruments"
                / "vmx3-power-supply" / "1.0.0" / "manifest.json"
            ).read_bytes()
        ).hexdigest(),
    }
    assert doc["advisories"] == []
    assert doc["support_contact"] == "https://github.com/northwind-instruments"
    _signature_verifies(clone, public)
    assert "status.json" in result.output


def test_publish_status_defaults_expiry_to_one_year_disclosed(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, _public = origin_key
    _ok(clone, "publish-status", RELEASE, "--origin-key", str(key_path))
    doc = _read_status(clone)
    updated = datetime.fromisoformat(doc["updated_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(doc["expires_at"].replace("Z", "+00:00"))
    assert timedelta(days=364) < expires - updated < timedelta(days=366)


def test_publish_status_refuses_when_a_status_already_exists(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, _public = origin_key
    _ok(clone, "publish-status", RELEASE, "--origin-key", str(key_path))
    output = _refuse(
        clone, "publish-status", RELEASE, "--origin-key", str(key_path),
    )
    assert "status_present:" in output


def test_publish_status_refuses_an_absent_release(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, _public = origin_key
    output = _refuse(
        clone, "publish-status", "northwind-instruments/osc-probe@9.9.9",
        "--origin-key", str(key_path),
    )
    assert "release_absent:" in output


def test_publish_status_refuses_a_manifest_that_disagrees_with_the_ref(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, _public = origin_key
    manifest = (
        clone / "releases" / "benchweave-registry" / "northwind-instruments"
        / "vmx3-power-supply" / "1.0.0" / "manifest.json"
    )
    doc = json.loads(manifest.read_bytes())
    doc["version"] = "0.0.1"
    manifest.write_text(json.dumps(doc))
    output = _refuse(clone, "publish-status", RELEASE, "--origin-key", str(key_path))
    assert "release_mismatch:" in output


def test_keyed_commands_refuse_when_the_clone_root_rejects_the_key(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    """The clone's committed origin root (F2) cross-checks the signing key:
    a mismatched key refuses instead of silently producing unresolvable bytes."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    other = Ed25519PrivateKey.generate()
    (clone / "keys").mkdir()
    (clone / "keys" / "main.pub.pem").write_bytes(
        other.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    key_path, _public = origin_key
    output = _refuse(
        clone, "publish-status", RELEASE, "--origin-key", str(key_path),
    )
    assert "origin_key_mismatch:" in output


def test_keyed_commands_accept_a_key_matching_the_clone_root(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    from cryptography.hazmat.primitives import serialization

    key_path, public = origin_key
    (clone / "keys").mkdir()
    (clone / "keys" / "main.pub.pem").write_bytes(
        public.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    _ok(clone, "publish-status", RELEASE, "--origin-key", str(key_path))
    _signature_verifies(clone, public)


# --- yank (CR-29's record half; the replay half is the registry lane's) -----------


def _publish(clone: Path, key_path: Path) -> None:
    _ok(
        clone, "publish-status", RELEASE, "--origin-key", str(key_path),
        "--expires-at", "2030-01-01T00:00:00Z",
    )


def test_yank_rewrites_sequence_plus_one_and_appends_the_record(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, public = origin_key
    _publish(clone, key_path)
    _ok(
        clone, "yank", RELEASE, "--origin-key", str(key_path),
        "--reason", "superseded by 1.1.0", "--actor", "registry-maintainer",
    )
    doc = _read_status(clone)
    _validate_schema(doc)
    assert doc["sequence"] == 2
    assert doc["lifecycle"] == "yanked"
    assert doc["reason"] == "superseded by 1.1.0"
    assert doc["advisories"] == []  # preserved, not reset
    assert doc["support_state"] == "maintained"  # preserved
    _signature_verifies(clone, public)
    record = json.loads(
        (
            clone / "records" / "lifecycle" / "northwind-instruments"
            / "vmx3-power-supply" / "1.0.0" / "2-yank.json"
        ).read_bytes()
    )
    assert record["record_type"] == "lifecycle"
    assert record["lifecycle"]["op"] == "yank"
    assert record["lifecycle"]["reason"] == "superseded by 1.1.0"
    assert record["actor"] == "registry-maintainer"
    assert record["lifecycle"]["status_sequence"] == 2
    assert record["lifecycle"]["release_manifest_sha256"] == doc["release"]["manifest_sha256"]


def test_yank_without_a_status_refuses_naming_publish_status(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, _public = origin_key
    output = _refuse(
        clone, "yank", RELEASE, "--origin-key", str(key_path),
        "--reason", "r", "--actor", "a",
    )
    assert "yank_status_absent:" in output
    assert "publish-status" in output


# --- advise (an advisory is not a yank) --------------------------------------------


def test_advise_appends_the_advisory_and_keeps_lifecycle_published(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, public = origin_key
    _publish(clone, key_path)
    _ok(
        clone, "advise", RELEASE, "--origin-key", str(key_path),
        "--actor", "registry-maintainer",
        "--id", "BW-2026-0001", "--severity", "medium",
        "--summary", "reading scaling bug under averaging",
        "--url", "https://example.invalid/advisories/BW-2026-0001",
    )
    doc = _read_status(clone)
    _validate_schema(doc)
    assert doc["sequence"] == 2
    assert doc["lifecycle"] == "published"  # an advisory is not a yank
    assert doc["advisories"] == [
        {
            "id": "BW-2026-0001",
            "severity": "medium",
            "summary": "reading scaling bug under averaging",
            "url": "https://example.invalid/advisories/BW-2026-0001",
        }
    ]
    _signature_verifies(clone, public)
    record = json.loads(
        (
            clone / "records" / "lifecycle" / "northwind-instruments"
            / "vmx3-power-supply" / "1.0.0" / "2-advisory.json"
        ).read_bytes()
    )
    assert record["lifecycle"]["op"] == "advisory"
    assert record["lifecycle"]["advisory"]["id"] == "BW-2026-0001"


def test_advise_stacks_advisories_in_order(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, _public = origin_key
    _publish(clone, key_path)
    for index in (1, 2):
        _ok(
            clone, "advise", RELEASE, "--origin-key", str(key_path),
            "--actor", "registry-maintainer",
            "--id", f"BW-2026-000{index}", "--severity", "low",
            "--summary", f"finding {index}", "--url",
            f"https://example.invalid/a/{index}",
        )
    doc = _read_status(clone)
    assert [entry["id"] for entry in doc["advisories"]] == ["BW-2026-0001", "BW-2026-0002"]
    assert doc["sequence"] == 3
    record_names = sorted(
        path.name
        for path in (
            clone / "records" / "lifecycle" / "northwind-instruments"
            / "vmx3-power-supply" / "1.0.0"
        ).iterdir()
    )
    assert record_names == ["1-publish.json", "2-advisory.json", "3-advisory.json"]


def test_advise_without_a_status_refuses_naming_publish_status(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, _public = origin_key
    output = _refuse(
        clone, "advise", RELEASE, "--origin-key", str(key_path),
        "--actor", "a", "--id", "X", "--severity", "low",
        "--summary", "s", "--url", "https://example.invalid/x",
    )
    assert "advisory_status_absent:" in output
    assert "publish-status" in output


def test_advise_refuses_a_duplicate_advisory_id(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, _public = origin_key
    _publish(clone, key_path)
    for _ in range(1):
        _ok(
            clone, "advise", RELEASE, "--origin-key", str(key_path),
            "--actor", "registry-maintainer", "--id", "BW-2026-0001",
            "--severity", "low", "--summary", "s",
            "--url", "https://example.invalid/x",
        )
    output = _refuse(
        clone, "advise", RELEASE, "--origin-key", str(key_path),
        "--actor", "registry-maintainer", "--id", "BW-2026-0001",
        "--severity", "low", "--summary", "s",
        "--url", "https://example.invalid/x",
    )
    assert "advisory_duplicate:" in output


def test_advise_validates_fields_before_writing(
    clone: Path, origin_key: tuple[Path, Any]
) -> None:
    key_path, _public = origin_key
    _publish(clone, key_path)
    output = _refuse(
        clone, "advise", RELEASE, "--origin-key", str(key_path),
        "--actor", "a", "--id", "X", "--severity", "catastrophic",
        "--summary", "s", "--url", "https://example.invalid/x",
    )
    assert "advisory_field_invalid:" in output
    output = _refuse(
        clone, "advise", RELEASE, "--origin-key", str(key_path),
        "--actor", "a", "--id", "X", "--severity", "low",
        "--summary", "s", "--url", "http://not-https.example/x",
    )
    assert "advisory_field_invalid:" in output
