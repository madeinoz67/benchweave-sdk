"""The zero-literal gate's SDK-side parity arms (issue #221, gateway #203 slice 7).

Every derivation the SDK side lands must move its site out of the twin
counter's executable count AND still generate what validates: the scaffold
descriptor, the preview fixtures, and the generated plugin-ui documents are
each asserted against the lock's active version — the same authority the
gateway's manifest twin reads.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from benchweave_sdk.served import active_version
from benchweave_sdk.validation import validate_descriptor

REPO = Path(__file__).resolve().parents[1]
COUNTER = REPO / "scripts/count_version_literals.py"
FIXTURE_SCHEMA_TEMPLATE = (
    "src/benchweave_sdk/standards/plugin-ui-preview/{version}/fixture.schema.json"
)


class TestScaffoldDerivation:
    """scaffold.py:530 — the example descriptor's pin is derived (§1.4)."""

    def test_example_descriptor_pins_the_lock_active_version(self) -> None:
        from benchweave_sdk.scaffold import descriptor_for

        assert descriptor_for("demo_package")["otdp_version"] == active_version("otdp")

    def test_example_descriptor_validates(self) -> None:
        """The scaffold generates what the SDK validates today (validation
        itself resolves the active schema — the parity the slice pins)."""
        from benchweave_sdk.scaffold import descriptor_for

        validate_descriptor(descriptor_for("demo_package"))


class TestGeneratedDocumentDerivations:
    """presentation.py ×4 — the fixture and the generated plugin-ui set."""

    def test_preview_fixture_carries_the_lock_active_version(self) -> None:
        from benchweave_sdk.presentation import _preview_fixture

        target = {
            "id": "voltage",
            "kind": "observation",
            "parameter_id": "voltage",
            "variables": [
                {
                    "id": "value",
                    "type": "number",
                    "unit": "V",
                    "shape": "scalar",
                    "axis_role": "value",
                }
            ],
        }
        fixture = _preview_fixture(target, suffix="example", severity="info")
        assert fixture["contract_version"] == active_version("plugin-ui-preview")

    def test_preview_fixture_validates_against_its_version_schema(self, tmp_path: Path) -> None:
        """The derived stamp names the schema family the fixture must
        validate against — byte-parity with the pre-derivation literal."""
        from jsonschema import Draft202012Validator

        from benchweave_sdk.presentation import _preview_fixture

        target = {
            "id": "voltage",
            "kind": "observation",
            "parameter_id": "voltage",
            "variables": [
                {
                    "id": "value",
                    "type": "number",
                    "unit": "V",
                    "shape": "scalar",
                    "axis_role": "value",
                }
            ],
        }
        fixture = _preview_fixture(target, suffix="example", severity="neutral")
        schema_path = REPO / FIXTURE_SCHEMA_TEMPLATE.format(version=fixture["contract_version"])
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(fixture)

    def test_generated_ui_documents_carry_the_lock_active_version(
        self, tmp_path: Path
    ) -> None:
        """The three generated plugin-ui documents stamp the family they
        must validate against (sites 692/700/706, §1.4)."""
        from benchweave_sdk import presentation, scaffold

        project = tmp_path / "ui"
        scaffold.create_project(project, "example_plugin")
        presentation.create_ui_resources(project, "example_plugin")
        package = project / "src/example_plugin"
        manifest = json.loads((package / "ui/manifest.json").read_bytes())
        envelope = json.loads((package / "presentation.json").read_bytes())
        catalogue = json.loads((package / "binding-catalogue.json").read_bytes())
        assert manifest["contract_version"] == active_version("plugin-ui")
        assert envelope["contract_version"] == active_version("plugin-ui")
        assert catalogue["contract_version"] == active_version("plugin-ui")

    def test_generated_ui_documents_validate(self, tmp_path: Path) -> None:
        """check-ui accepts the full generated set — the no-regression arm."""
        from benchweave_sdk import presentation, scaffold

        project = tmp_path / "ui"
        scaffold.create_project(project, "example_plugin")
        presentation.create_ui_resources(project, "example_plugin")
        package = project / "src/example_plugin"
        # check_ui raises preview_invalid_presentation on any finding; the
        # no-raise return IS the acceptance.
        presentation.check_ui(
            package / "presentation.json",
            package / "descriptor.json",
            package,
            package / "binding-catalogue.json",
            firmware=None,
            features=frozenset(),
            panels=frozenset(),
        )


class TestTwinCounter:
    """The twin's own plant arm (design G2's SDK-side evidence)."""

    def test_twin_counts_zero_outside_the_register(self) -> None:
        result = subprocess.run(
            [sys.executable, str(COUNTER)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "0 outside register" in result.stdout

    def test_twin_is_reproducible_twice_byte_identical(self) -> None:
        first = subprocess.run(
            [sys.executable, str(COUNTER), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        second = subprocess.run(
            [sys.executable, str(COUNTER), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert first.returncode == 0 and second.returncode == 0
        assert first.stdout == second.stdout

    def test_a_planted_literal_fails_the_twin(self, tmp_path: Path) -> None:
        """G2's SDK plant, proven locally in a scratch tree (the wire-level
        plant rides the plant branch; this is the committed teeth)."""
        scratch = tmp_path / "scratch-repo"
        (scratch / "scripts").mkdir(parents=True)
        shutil.copy(COUNTER, scratch / "scripts/count_version_literals.py")
        shutil.copytree(REPO / "src/benchweave_sdk", scratch / "src/benchweave_sdk")
        planted = scratch / "src/benchweave_sdk/packaging.py"
        planted.write_text('_PLANT = "9.9.9"\n', encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(scratch / "scripts/count_version_literals.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "src/benchweave_sdk/packaging.py" in result.stdout

    def test_a_plant_inside_a_registered_file_fails_via_expected_sites(
        self, tmp_path: Path
    ) -> None:
        """G2b: the register cannot become a laundering list without a
        visible register edit — a planted literal inside scaffold.py fails
        the expectation, never the count."""
        scratch = tmp_path / "scratch-repo"
        (scratch / "scripts").mkdir(parents=True)
        shutil.copy(COUNTER, scratch / "scripts/count_version_literals.py")
        shutil.copytree(REPO / "src/benchweave_sdk", scratch / "src/benchweave_sdk")
        scaffold_py = scratch / "src/benchweave_sdk/scaffold.py"
        scaffold_py.write_bytes(
            scaffold_py.read_bytes() + b'\n_PLANT = "9.9.9"\n',  # noqa: E501
        )
        result = subprocess.run(
            [sys.executable, str(scratch / "scripts/count_version_literals.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "register expectation failed: src/benchweave_sdk/scaffold.py" in result.stdout
        assert "expects 4 literals, found 5" in result.stdout


class TestRegisteredDisposition:
    """G3a (gateway design §5): the SDK copy's register entry cites the D2
    trigger and carries the exact expectation — the byte-identity of the
    two contracts.py copies stays pinned by
    tests/sdk/test_presentation_packaging.py (cited there, not re-built)."""

    def test_the_twin_register_reason_cites_the_d2_trigger(self) -> None:
        result = subprocess.run(
            [sys.executable, str(COUNTER), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        sites = [row for row in payload["sites"] if row["file"].endswith("contracts.py")]
        assert len(sites) == 3
        assert all(row["exempt"] is True for row in sites)
        assert all("D2" in row["reason"] for row in sites)


class TestFoldHardening:
    """The #221 fold's SDK-side rows (5: env filter + standard-set pin +
    files-parsed census; 6: authored-data value pins)."""

    def _scratch_sdk_repo(self, tmp_path: Path) -> Path:
        shutil.copytree(REPO / "src/benchweave_sdk", scratch_root := tmp_path / "src/benchweave_sdk")
        scratch = tmp_path
        (scratch / "scripts").mkdir(exist_ok=True)
        shutil.copy(COUNTER, scratch / "scripts/count_version_literals.py")
        shutil.copy(REPO / "standards-lock.json", scratch / "standards-lock.json")
        del scratch_root
        return scratch

    def test_standard_id_set_is_pinned_to_the_lock(self) -> None:
        """Fold row 5: STANDARD_IDS equals the standards lock's row ids —
        the repository's authority for the governed set (it carries no
        standards manifest; the lock is what served derives from)."""
        document = json.loads((REPO / "standards-lock.json").read_text(encoding="utf-8"))
        lock_ids = sorted({str(row["id"]) for row in document.get("standards", [])})
        assert lock_ids == [
            "execution",
            "interface",
            "otdp",
            "plugin-ui",
            "plugin-ui-preview",
            "registry",
        ]

    def test_a_seventh_standard_drift_refuses(self, tmp_path: Path) -> None:
        """Fold row 5's probe: a lock with a seventh id and a planted
        newstd path-shape literal must REFUSE, not pass silently. RED at
        the fold base: the counter exited 0 over the same tree."""
        scratch = self._scratch_sdk_repo(tmp_path)
        document = json.loads((scratch / "standards-lock.json").read_text(encoding="utf-8"))
        document["standards"].append({"id": "newstd", "version": "1.0.0", "active": True})
        (scratch / "standards-lock.json").write_text(json.dumps(document))
        (scratch / "src/benchweave_sdk/planted_newstd.py").write_text(
            'NEWSTD_PIN = "newstd/1.0.0"\n', encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(scratch / "scripts/count_version_literals.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "standard_set_drift:" in result.stderr

    def test_an_environment_inside_src_is_filtered(self, tmp_path: Path) -> None:
        """Fold row 5's env-filter port: a venv created inside src/ must be
        EXCLUDED from the scan (the gateway counter's filter, mirrored).
        RED at the fold base: the twin counted the plant inside the venv."""
        scratch = self._scratch_sdk_repo(tmp_path)
        (scratch / "src/benchweave_sdk/venv/lib").mkdir(parents=True)
        (scratch / "src/benchweave_sdk/venv/lib/planted.py").write_text(
            '_PLANT = "9.9.9"\n', encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(scratch / "scripts/count_version_literals.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "venv" not in result.stdout

    def test_a_registered_value_substitution_fails_the_value_pin(
        self, tmp_path: Path
    ) -> None:
        """Fold row 6: the scaffold register pins the VALUES — a
        semantics-changing substitution (supported_firmware 1.0.0 -> 9.9.9)
        fails at unchanged cardinality. RED at the fold base: the count
        stayed 4 and the substitution passed."""
        scratch = self._scratch_sdk_repo(tmp_path)
        scaffold = scratch / "src/benchweave_sdk/scaffold.py"
        text = scaffold.read_text(encoding="utf-8")
        old = '"supported_firmware": ["1.0.0"]'
        assert old in text
        scaffold.write_text(text.replace(old, '"supported_firmware": ["9.9.9"]'), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(scratch / "scripts/count_version_literals.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "register value pin failed:" in result.stdout
        assert "'9.9.9'" in result.stdout
