"""Issue #541 slice 2: ``migrate-ui`` re-stamps the class-reference
ledger (standards record §8 — the ledger joins the re-stamp set).

The fixture is a real derived project whose descriptor pins a composed
action class: ``derive-ui`` writes the birth ledger with ``custom_actions``
and the slice-2 ``composed_actions``/``composed_classes`` rows at the
active family. The stale ledger is the same bytes with the family stamps
targeted down to the PREVIOUS family version (``0.3.0`` — a real
historical row, the same discipline as ``test_migrate_ui.OLD``), so the
re-stamp arm runs the actual 0.3.0 -> 0.4.0 family bump the lock just
took. The migration target is always derived from the lock at run time.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchweave_sdk import cli
from benchweave_sdk.classref import declaration_scaffold, derive_ui, find_reference
from benchweave_sdk.scaffold import create_project
from benchweave_sdk.served import active_version

FIXTURES = Path(__file__).parent / "fixtures" / "classref"
REFERENCE = find_reference("otdp.logic_analyser/1.0.0")
PACKAGE = "veridian_composed_plugin"
STAGE_URN = "otdp.veridian_staging.ghost_stage/1.0.0"
CLASS_URN = "otdp.action.veridian_staging/1.0.0"

#: The previous family version (a real carried row) — fixture INPUT for
#: the down-stamped ledger, never a generated stamp.
OLD_FAMILY = "0.3.0"
_ACTIVE_FAMILY = active_version("plugin-ui-class-reference")


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _composed_document() -> dict[str, Any]:
    return json.loads((FIXTURES / "composed-staging.json").read_bytes())


def _descriptor(document: dict[str, Any]) -> dict[str, Any]:
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["actions"][STAGE_URN] = {
        "binding": {"kind": "adapter", "key": "ghost_stage"},
        "input_constraints": {},
        "timeout_ms": 1000,
        "side_effect": "state_change",
        "cancellable": True,
        "retry": "never",
    }
    descriptor["contracts"].append(
        {
            "id": "urn:veridian:composed-staging:1.0.0",
            "path": "composed-staging.json",
            "sha256": hashlib.sha256(_raw(document)).hexdigest(),
        }
    )
    return descriptor


def _composed_project(
    destination: Path, extra_actions: dict[str, Any] | None = None
) -> Path:
    """A real scaffolded plugin carrying a composed class pin and the
    derived document set, with the birth ledger written at the active
    family (the migrate-ui input). ``extra_actions`` declares additional
    descriptor actions (the N5 arms add a residual member so the birth
    ledger carries custom_actions beside the composed rows)."""
    document = _composed_document()
    descriptor = _descriptor(document)
    if extra_actions:
        descriptor["actions"].update(extra_actions)
    create_project(destination, PACKAGE, with_ui=False)
    package = destination / "src" / PACKAGE
    (package / "composed-staging.json").write_bytes(_raw(document))
    for pinned in ("vendor-catalog.json", "vectors-f1.json"):
        (package / pinned).write_bytes((FIXTURES / pinned).read_bytes())
    descriptor_path = package / "descriptor.json"
    descriptor_path.write_bytes(_raw(descriptor))
    derived = derive_ui(
        _raw(descriptor), REFERENCE, descriptor_path=descriptor_path
    )
    ui = package / "ui"
    ui.mkdir(exist_ok=True)
    (ui / "manifest.json").write_bytes(_raw(derived.manifest))
    (package / "presentation.json").write_bytes(_raw(derived.envelope))
    (package / "binding-catalogue.json").write_bytes(_raw(derived.catalogue))
    settings = ui / "settings"
    settings.mkdir(exist_ok=True)
    (settings / "configure.schema.json").write_bytes(_raw(derived.settings_schema))
    presets = ui / "presets"
    presets.mkdir(exist_ok=True)
    for slug, row in derived.preset_scaffolds.items():
        (presets / f"{slug}.json").write_bytes(_raw(row))
    (ui / "class-reference.json").write_bytes(_raw(declaration_scaffold(derived)))
    return package


#: A residual member for the N5 arms: declared by the descriptor,
#: described by no catalog and claimed by no class — the birth ledger
#: carries it in custom_actions.
RESIDUAL_URN = "otdp.veridian_staging.uncovered/1.0.0"


def _composed_and_residual_project(destination: Path) -> Path:
    return _composed_project(
        destination,
        extra_actions={
            RESIDUAL_URN: {
                "binding": {"kind": "adapter", "key": "uncovered"},
                "input_constraints": {},
                "timeout_ms": 1000,
                "side_effect": "none",
                "cancellable": True,
                "retry": "never",
            }
        },
    )


def _downstamp_ledger(package: Path) -> bytes:
    """The stale-ledger fixture: the family stamps and the validation
    records down-substituted to the previous family version, byte-in-place
    (the exact shape a ledger last touched before the family bump
    carried)."""
    ledger_path = package / "ui" / "class-reference.json"
    raw = ledger_path.read_bytes()
    for key in ("contract_version", "reference_version", "validated_against"):
        needle = f'"{key}": "{_ACTIVE_FAMILY}"'.encode()
        replacement = f'"{key}": "{OLD_FAMILY}"'.encode()
        raw = raw.replace(needle, replacement)
    ledger_path.write_bytes(raw)
    return raw


def _migrate(monkeypatch: pytest.MonkeyPatch, package: Path) -> int:
    return cli.main(
        [
            "migrate-ui",
            str(package / "presentation.json"),
            "--descriptor",
            str(package / "descriptor.json"),
            "--resources",
            str(package),
            "--catalogue",
            str(package / "binding-catalogue.json"),
        ]
    )


def _tree(root: Path) -> dict[str, bytes]:
    return {
        entry.relative_to(root).as_posix(): entry.read_bytes()
        for entry in sorted(root.rglob("*"))
        if entry.is_file()
        and not ({"__pycache__", ".pytest_cache", ".git"} & set(entry.parts))
    }


def test_ledger_restamps_across_the_family_bump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A6 (standards record §10): a clean stale ledger re-stamps exactly
    the stamp kinds — the two family stamps and each
    ``composed_classes[].validated_against`` — and no content byte: the
    parsed documents differ only in those values, and nothing else in the
    project tree moves (the plugin-ui documents are already current, so
    the ledger is the whole motion)."""
    package = _composed_project(tmp_path / "project")
    stale_raw = _downstamp_ledger(package)
    before = _tree(package)
    code = _migrate(monkeypatch, package)
    assert code == 0
    after = _tree(package)
    moved = {name for name in before if before[name] != after.get(name)}
    assert moved == {"ui/class-reference.json"}, sorted(moved)
    stale = json.loads(stale_raw)
    migrated = json.loads(after["ui/class-reference.json"])
    assert migrated["contract_version"] == _ACTIVE_FAMILY
    assert migrated["reference_version"] == _ACTIVE_FAMILY
    assert all(
        row["validated_against"] == _ACTIVE_FAMILY
        for row in migrated["composed_classes"]
    )
    # Version strings ONLY: every other value in the document is
    # byte-equal, including the class URN's own version (content, never
    # re-stamped).
    def _strip(document: dict[str, Any]) -> dict[str, Any]:
        stripped = json.loads(json.dumps(document))
        stripped.pop("contract_version")
        stripped.pop("reference_version")
        for row in stripped.get("composed_classes", []):
            row["validated_against"] = None
        return stripped

    assert _strip(migrated) == _strip(stale)
    assert migrated["composed_classes"] == [
        {"class": CLASS_URN, "validated_against": _ACTIVE_FAMILY}
    ]


def test_current_ledger_is_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project whose plugin-ui documents AND ledger all carry the
    active versions is a no-op: nothing written."""
    package = _composed_project(tmp_path / "noop")
    before = _tree(package)
    assert _migrate(monkeypatch, package) == 0
    assert _tree(package) == before


def test_unresolved_pin_refuses_nothing_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ledger-named class whose pin is gone from the package refuses
    ``migrate_ui_composed_unresolved`` with nothing written."""
    package = _composed_project(tmp_path / "gone")
    _downstamp_ledger(package)
    (package / "composed-staging.json").unlink()
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    assert "migrate_ui_composed_unresolved:" in capsys.readouterr().err
    assert _tree(package) == before


def test_digest_moved_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A pin whose bytes moved under its sha256 refuses unresolved — the
    validation stamp cannot ride a digest that no longer verifies."""
    package = _composed_project(tmp_path / "digest")
    _downstamp_ledger(package)
    document = _composed_document()
    document["title"] = "Veridian numeric staging (moved)"
    (package / "composed-staging.json").write_bytes(_raw(document))
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    rendered = capsys.readouterr().err
    assert "migrate_ui_composed_unresolved:" in rendered
    assert "digest moved" in rendered
    assert _tree(package) == before


def test_urn_mismatch_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ledger naming a class urn no pin declares refuses unresolved —
    the recorded validation cannot be re-attributed to a different
    document."""
    package = _composed_project(tmp_path / "mismatch")
    _downstamp_ledger(package)
    ledger_path = package / "ui" / "class-reference.json"
    ledger = json.loads(ledger_path.read_bytes())
    ledger["composed_classes"][0]["class"] = (
        "otdp.action.veridian_staging_alt/1.0.0"
    )
    ledger_path.write_bytes(_raw(ledger))
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    assert "migrate_ui_composed_unresolved:" in capsys.readouterr().err
    assert _tree(package) == before


def test_schema_invalid_under_target_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A pinned document that no longer validates under the target
    family's composed schema refuses unresolved — the re-stamp only rides
    bytes the target schema admits."""
    package = _composed_project(tmp_path / "invalid")
    _downstamp_ledger(package)
    document = _composed_document()
    document["side_effect"] = "configuration_write"
    raw = _raw(document)
    (package / "composed-staging.json").write_bytes(raw)
    descriptor = json.loads((package / "descriptor.json").read_bytes())
    for row in descriptor["contracts"]:
        if row["path"] == "composed-staging.json":
            row["sha256"] = hashlib.sha256(raw).hexdigest()
    (package / "descriptor.json").write_bytes(_raw(descriptor))
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    assert "migrate_ui_composed_unresolved:" in capsys.readouterr().err
    assert _tree(package) == before


def test_ledger_drift_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ledger whose composed inventory disagrees with set arithmetic
    over the current descriptor and pins refuses
    ``migrate_ui_ledger_drift`` — the project needs derive-ui, not a
    version write."""
    package = _composed_project(tmp_path / "drift")
    _downstamp_ledger(package)
    ledger_path = package / "ui" / "class-reference.json"
    ledger = json.loads(ledger_path.read_bytes())
    ledger["composed_actions"].append(
        {
            "action": "otdp.veridian_staging.unclaimed/1.0.0",
            "resolution": "composed",
            "class": CLASS_URN,
        }
    )
    ledger_path.write_bytes(_raw(ledger))
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    rendered = capsys.readouterr().err
    assert "migrate_ui_ledger_drift:" in rendered
    assert "unclaimed" in rendered
    assert _tree(package) == before


def test_ledger_above_active_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ledger above the active family refuses ``migrate_ui_ahead`` —
    migrate-ui never writes versions down, the ledger included."""
    package = _composed_project(tmp_path / "ahead")
    ledger_path = package / "ui" / "class-reference.json"
    raw = ledger_path.read_bytes()
    major = int(_ACTIVE_FAMILY.split(".")[0])
    ahead = f"{major + 1}.0.0"
    for key in ("contract_version", "reference_version"):
        raw = raw.replace(
            f'"{key}": "{_ACTIVE_FAMILY}"'.encode(),
            f'"{key}": "{ahead}"'.encode(),
        )
    ledger_path.write_bytes(raw)
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    assert "migrate_ui_ahead:" in capsys.readouterr().err
    assert _tree(package) == before


# ---------------------------------------------------------------------------
# The 2026-10-23 fold wave (review rows B4/B6). Each arm names its row;
# the RED evidence for every arm is quoted in the fold commit's message.
# ---------------------------------------------------------------------------


def test_b4_validated_against_not_version_shaped_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """B4: a ``validated_against`` that is not version-shaped refuses
    ``migrate_ui_version_absent`` — the re-stamp never OVERWRITES a
    malformed stamp (mirroring the family stamps' guard; the pre-fold
    walk silently wrote ``"not-a-version"`` down to the target)."""
    package = _composed_project(tmp_path / "va-shape")
    ledger_path = package / "ui" / "class-reference.json"
    ledger = json.loads(ledger_path.read_bytes())
    ledger["composed_classes"][0]["validated_against"] = "not-a-version"
    ledger_path.write_bytes(_raw(ledger))
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    rendered = capsys.readouterr().err
    assert "migrate_ui_version_absent:" in rendered
    assert "validated_against" in rendered
    assert _tree(package) == before


def test_b4_validated_against_above_target_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """B4's ahead guard: a ``validated_against`` above the target family
    refuses ``migrate_ui_ahead`` — migrate-ui never writes versions down,
    the validation record included (the pre-fold walk wrote ``"9.0.0"``
    DOWN to the target, exit 0). The existing ahead arm forged only the
    family stamps; this one forges the record."""
    package = _composed_project(tmp_path / "va-ahead")
    ledger_path = package / "ui" / "class-reference.json"
    ledger = json.loads(ledger_path.read_bytes())
    ledger["composed_classes"][0]["validated_against"] = "9.0.0"
    ledger_path.write_bytes(_raw(ledger))
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    rendered = capsys.readouterr().err
    assert "migrate_ui_ahead:" in rendered
    assert "9.0.0" in rendered
    assert _tree(package) == before


def test_b6_deleted_composed_classes_rows_refuse_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """B6 (lane B F2): a ledger whose ``composed_classes`` rows were
    deleted refuses ``migrate_ui_ledger_drift`` — the class set is part of
    the drift arithmetic, so the next family bump cannot re-stamp family
    stamps without re-resolving the now-unnamed classes (the pre-fold
    walk discarded the derived class set and exited 0)."""
    package = _composed_project(tmp_path / "drift-deleted")
    _downstamp_ledger(package)
    ledger_path = package / "ui" / "class-reference.json"
    ledger = json.loads(ledger_path.read_bytes())
    ledger["composed_classes"] = []
    ledger_path.write_bytes(_raw(ledger))
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    rendered = capsys.readouterr().err
    assert "migrate_ui_ledger_drift:" in rendered
    assert "composed_classes" in rendered
    assert _tree(package) == before


def test_b6_forged_composed_classes_row_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """B6's forged direction refuses EARLIER in the pipeline: a class row
    naming a class no pin declares fails the re-resolution walk first and
    refuses ``migrate_ui_composed_unresolved`` (the design's §8.3 ordering
    — re-resolution runs before the inventory walk), so the class-set
    arithmetic's upper bound is reachable only through deletion and
    malformed rows. This arm pins that precedence: a forged class row
    can never pass silently, whichever code refuses it."""
    package = _composed_project(tmp_path / "drift-forged")
    _downstamp_ledger(package)
    ledger_path = package / "ui" / "class-reference.json"
    ledger = json.loads(ledger_path.read_bytes())
    ledger["composed_classes"].append(
        {"class": "otdp.action.veridian_ghost/1.0.0", "validated_against": OLD_FAMILY}
    )
    ledger_path.write_bytes(_raw(ledger))
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    rendered = capsys.readouterr().err
    assert "migrate_ui_composed_unresolved:" in rendered
    assert "otdp.action.veridian_ghost/1.0.0" in rendered
    assert _tree(package) == before


# ---------------------------------------------------------------------------
# The rider wave (NITs N3/N4/N5, 2026-10-23). Each arm names its row.
# ---------------------------------------------------------------------------


def test_n3_non_object_descriptor_refuses_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """N3: a non-object descriptor with a ledger present refuses typed
    (``migrate_ui_version_absent``) — the pre-fold walk crashed on a bare
    ``AttributeError`` (``.get`` on a list) inside the ledger motion. No
    write occurs either way, but a bare exception is not an SDK error
    face (the same class as B7's bare TypeError)."""
    package = _composed_project(tmp_path / "non-object-descriptor")
    _downstamp_ledger(package)
    (package / "descriptor.json").write_bytes(b'["not", "an", "object"]\n')
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    rendered = capsys.readouterr().err
    assert "migrate_ui_version_absent:" in rendered
    assert "not a JSON object" in rendered
    assert _tree(package) == before


def test_n4_progress_line_names_only_the_moved_stamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """N4: the migration line reports what moved — when only
    ``reference_version`` is stale, the line names reference_version with
    its own old value, never a misleading
    ``plugin-ui-class-reference 0.4.0 -> 0.4.0`` summary."""
    package = _composed_project(tmp_path / "line")
    ledger_path = package / "ui" / "class-reference.json"
    raw = ledger_path.read_bytes().replace(
        f'"reference_version": "{_ACTIVE_FAMILY}"'.encode(),
        b'"reference_version": "0.3.0"',
    )
    ledger_path.write_bytes(raw)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 0
    # The CLI wraps long lines; the assertion runs over whitespace-normalized
    # output so it reads the line's content, not its terminal wrapping.
    flat = " ".join(capsys.readouterr().out.split())
    assert "reference_version 0.3.0 -> " in flat
    assert f"{_ACTIVE_FAMILY} -> {_ACTIVE_FAMILY}" not in flat


def test_n5_custom_inventory_drift_refuses_when_ledger_omits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """N5, the derived-but-omitted direction for the CUSTOM inventory: a
    ledger whose ``custom_actions`` drops a derived residual member
    refuses ``migrate_ui_ledger_drift``. (Coverage pin: the arithmetic is
    slice 2's first cut; the review's gap was that no arm exercised this
    direction — no RED claimed.)"""
    package = _composed_and_residual_project(tmp_path / "custom-omit")
    _downstamp_ledger(package)
    ledger_path = package / "ui" / "class-reference.json"
    ledger = json.loads(ledger_path.read_bytes())
    assert ledger["custom_actions"], "the project must derive a residual member"
    ledger["custom_actions"] = []
    ledger_path.write_bytes(_raw(ledger))
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    rendered = capsys.readouterr().err
    assert "migrate_ui_ledger_drift:" in rendered
    assert "custom" in rendered
    assert _tree(package) == before


def test_n5_forged_custom_row_refuses_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """N5, the ledger-extra direction for the custom inventory: a forged
    ``custom_actions`` row naming an URN the derivation holds as neither
    residual nor anything else refuses drift. (Coverage pin, no RED
    claimed — the behavior is the first cut's.)"""
    package = _composed_and_residual_project(tmp_path / "custom-forged")
    _downstamp_ledger(package)
    ledger_path = package / "ui" / "class-reference.json"
    ledger = json.loads(ledger_path.read_bytes())
    ledger["custom_actions"].append(
        {
            "action": "com.veridian-labs.nope/1.0.0",
            "resolution": "custom",
            "reason": "forged",
        }
    )
    ledger_path.write_bytes(_raw(ledger))
    before = _tree(package)
    capsys.readouterr()
    assert _migrate(monkeypatch, package) == 1
    rendered = capsys.readouterr().err
    assert "migrate_ui_ledger_drift:" in rendered
    assert "nope" in rendered
    assert _tree(package) == before
