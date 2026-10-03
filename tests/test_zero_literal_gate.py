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

import pytest

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

    def test_twin_census_is_pinned(self) -> None:
        """Fold wave row 1's observability half: the scanned-file census is
        pinned (20 sdk files + 13 server files at the current head — slice
        B's scenarios.py is the 33rd file) — a scope change is a visible
        diff, never a silent denominator move. The server half is issue
        #309 slice A's scope extension: deleting the tree or narrowing
        the roots reds here."""
        result = subprocess.run(
            [sys.executable, str(COUNTER), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["scanned"] == 33, (
            "the scanned-file census moved — update this pin in the "
            "same commit as the tree change (the ratchet discipline)"
        )

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

    def test_the_scope_names_the_server_tree(self) -> None:
        """#309 slice A: the lane's denominator names both source roots —
        the server tree is inside the gate, not an uncounted passenger."""
        result = subprocess.run(
            [sys.executable, str(COUNTER)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "src/benchweave_sdk_server" in result.stdout

    def test_a_plant_in_the_server_tree_fails_the_twin(self, tmp_path: Path) -> None:
        """The extension has teeth: a literal planted under
        src/benchweave_sdk_server/ REFUSES — pre-extension this same tree
        passed (the counter did not walk the server root at all)."""
        scratch = tmp_path / "scratch-repo"
        (scratch / "scripts").mkdir(parents=True)
        shutil.copy(COUNTER, scratch / "scripts/count_version_literals.py")
        shutil.copy(REPO / "standards-lock.json", scratch / "standards-lock.json")
        shutil.copytree(REPO / "src/benchweave_sdk", scratch / "src/benchweave_sdk")
        shutil.copytree(
            REPO / "src/benchweave_sdk_server", scratch / "src/benchweave_sdk_server"
        )
        planted = scratch / "src/benchweave_sdk_server/session.py"
        planted.write_text('_PLANT = "9.9.9"\n', encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(scratch / "scripts/count_version_literals.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "src/benchweave_sdk_server/session.py" in result.stdout

    def test_a_missing_server_root_refuses(self, tmp_path: Path) -> None:
        """A scope half that vanished is a count that cannot be computed:
        the run REFUSES (version_literal_count_failed naming the missing
        root), never scans the survivor and passes as if nothing was gone."""
        scratch = tmp_path / "scratch-repo"
        (scratch / "scripts").mkdir(parents=True)
        shutil.copy(COUNTER, scratch / "scripts/count_version_literals.py")
        shutil.copy(REPO / "standards-lock.json", scratch / "standards-lock.json")
        shutil.copytree(REPO / "src/benchweave_sdk", scratch / "src/benchweave_sdk")
        result = subprocess.run(
            [sys.executable, str(scratch / "scripts/count_version_literals.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "version_literal_count_failed" in result.stderr
        assert "benchweave_sdk_server" in result.stderr

    def test_a_planted_literal_fails_the_twin(self, tmp_path: Path) -> None:
        """G2's SDK plant, proven locally in a scratch tree (the wire-level
        plant rides the plant branch; this is the committed teeth)."""
        scratch = tmp_path / "scratch-repo"
        (scratch / "scripts").mkdir(parents=True)
        shutil.copy(COUNTER, scratch / "scripts/count_version_literals.py")
        shutil.copy(REPO / "standards-lock.json", scratch / "standards-lock.json")
        shutil.copytree(REPO / "src/benchweave_sdk", scratch / "src/benchweave_sdk")
        shutil.copytree(
            REPO / "src/benchweave_sdk_server", scratch / "src/benchweave_sdk_server"
        )
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

    def test_an_assembled_plant_fails_the_twin(self, tmp_path: Path) -> None:
        """Issue #269 row 1: CONSTANT-ONLY assembly is caught — a version
        assembled from literals (``"9." + "9.9"``) refuses with an ASM
        pattern row. RED at the twin's fold base: the pre-fold twin passed
        over the same tree (the assembly was invisible to the text scan)."""
        scratch = tmp_path / "scratch-repo"
        (scratch / "scripts").mkdir(parents=True)
        shutil.copy(COUNTER, scratch / "scripts/count_version_literals.py")
        shutil.copy(REPO / "standards-lock.json", scratch / "standards-lock.json")
        shutil.copytree(REPO / "src/benchweave_sdk", scratch / "src/benchweave_sdk")
        shutil.copytree(
            REPO / "src/benchweave_sdk_server", scratch / "src/benchweave_sdk_server"
        )
        planted = scratch / "src/benchweave_sdk/packaging.py"
        planted.write_text('_PLANT = "9." + "9.9"\n', encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(scratch / "scripts/count_version_literals.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "ASM-BARE" in result.stdout
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
        shutil.copy(REPO / "standards-lock.json", scratch / "standards-lock.json")
        shutil.copytree(REPO / "src/benchweave_sdk", scratch / "src/benchweave_sdk")
        shutil.copytree(
            REPO / "src/benchweave_sdk_server", scratch / "src/benchweave_sdk_server"
        )
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
        scratch = tmp_path
        shutil.copytree(REPO / "src/benchweave_sdk", scratch / "src/benchweave_sdk")
        shutil.copytree(
            REPO / "src/benchweave_sdk_server", scratch / "src/benchweave_sdk_server"
        )
        (scratch / "scripts").mkdir(exist_ok=True)
        shutil.copy(COUNTER, scratch / "scripts/count_version_literals.py")
        shutil.copy(REPO / "standards-lock.json", scratch / "standards-lock.json")
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
        """A MARKER-carrying environment inside src/ is EXCLUDED from the
        scan (issue #269 §3.2: the marker rule — the directory carries
        ``pyvenv.cfg``). Under the fold's name-set filter this arm passed
        by NAME alone; the marker is now what excludes."""
        scratch = self._scratch_sdk_repo(tmp_path)
        (scratch / "src/benchweave_sdk/venv/lib").mkdir(parents=True)
        (scratch / "src/benchweave_sdk/venv/bin").mkdir()
        (scratch / "src/benchweave_sdk/venv/pyvenv.cfg").write_text(
            "home = /usr/bin\n", encoding="utf-8"
        )
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

    def test_a_venv_name_without_marker_is_scanned(self, tmp_path: Path) -> None:
        """Issue #269 §3.2, the collision case: a directory merely NAMED
        ``venv`` carries project code until it carries the marker — its
        literals are SCANNED and REFUSE. RED at the twin's rule base: the
        name-set filter excluded the same tree silently (exit 0)."""
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
        assert result.returncode == 1, result.stdout + result.stderr
        assert "unregistered literal: src/benchweave_sdk/venv/lib/planted.py" in (
            result.stdout
        )

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


class TestRegisterPinDefense:
    """Fold wave row 7 (adv-lane2 L4): the twin's REGISTER lives in the
    counter's NON-shared region — the gateway parity pin cannot see an
    edit to it, and before this class nothing in the SDK suite caught
    one. The register rows are pinned here against test literals; the
    mutation and redirect arms prove the defenses fire."""

    def _counter_register(
        self, path: Path
    ) -> dict[str, tuple[str, int, tuple[str, ...] | None]]:
        import importlib

        spec = importlib.util.spec_from_file_location("twin_under_test", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.REGISTER

    def test_twin_register_rows_are_pinned(self) -> None:
        """The committed register's row set, expectations and value pins
        are pinned in the SDK suite — a REGISTER edit is now a visible
        suite diff, never a silent loosening."""
        register = self._counter_register(COUNTER)
        assert set(register) == {
            "src/benchweave_sdk/standards/plugin-ui/contracts.py",
            "src/benchweave_sdk/scaffold.py",
            "src/benchweave_sdk/publishing.py",
            "src/benchweave_sdk/registry_ops.py",
        }
        contracts = register["src/benchweave_sdk/standards/plugin-ui/contracts.py"]
        assert contracts[1] == 3
        assert contracts[2] is None  # digest-pinned whole, no value pin
        scaffold = register["src/benchweave_sdk/scaffold.py"]
        assert scaffold[1] == 4
        assert scaffold[2] == ("0.1.0", "0.1.0", "0.1.0", "1.0.0")
        publishing = register["src/benchweave_sdk/publishing.py"]
        assert publishing[1] == 3
        assert publishing[2] == ("0.1.1", "0.0.0", "0.1.0")
        registry_ops = register["src/benchweave_sdk/registry_ops.py"]
        assert registry_ops[1] == 1
        assert registry_ops[2] == ("1.1.0",)

    def test_a_register_edit_is_detected_by_the_pin(self, tmp_path: Path) -> None:
        """The pin's teeth: a scratch copy with the scaffold expectation
        loosened (4 -> 5) fails the same comparison the committed pin
        makes."""
        scratch = tmp_path / "twin-register-edited.py"
        text = COUNTER.read_text(encoding="utf-8")
        edited = text.replace('4,\n        ("0.1.0"', '5,\n        ("0.1.0"')
        assert edited != text, "the mutation arm's needle vanished from the twin"
        scratch.write_text(edited, encoding="utf-8")
        register = self._counter_register(scratch)
        with pytest.raises(AssertionError):
            assert register["src/benchweave_sdk/scaffold.py"][1] == 4

    def test_a_lock_path_redirect_fails_loudly(self, tmp_path: Path) -> None:
        """The standard-set pin reads the COMMITTED lock path: a redirected
        counter copy (lock path edited) fails its run with the
        count-failed prefix — a silent re-authority is not representable."""
        scratch = tmp_path / "scratch-redirect"
        (scratch / "scripts").mkdir(parents=True)
        text = COUNTER.read_text(encoding="utf-8")
        redirected = text.replace(
            'REPO_ROOT / "standards-lock.json"',
            'REPO_ROOT / "standards-lock-redirected.json"',
        )
        assert redirected != text, "the redirect arm's needle vanished"
        (scratch / "scripts/count_version_literals.py").write_text(
            redirected, encoding="utf-8"
        )
        (scratch / "standards-lock.json").write_text('{"standards": []}')
        result = subprocess.run(
            [sys.executable, str(scratch / "scripts/count_version_literals.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "version_literal_count_failed" in result.stderr


class TestUnreadableRootRefuses:
    """PR #90 carry-forward row R5 (prepared, uncommitted): pathlib's rglob
    swallows PermissionError, so an UNREADABLE source root scanned zero
    files and exited 0 — the denominator narrowed silently. The counter
    must refuse instead (the same direction as the missing-root rule)."""

    def _counter(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "count_version_literals_under_test", COUNTER
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def _armed_counter(self, tmp_path, monkeypatch, roots):
        """A counter whose REPO_ROOT and SOURCE_ROOTS live under tmp_path,
        with a minimal matching standards-lock so main() reaches the scan
        (otherwise the missing lock refuses first and hides the class under
        test — observed: the base then exits 1 via the lock error while the
        fixture path's own 'unreadable' substring made the phrase assert
        pass VACUOUSLY; the arms assert the full refusal phrase instead)."""
        counter = self._counter()
        lock_ids = [
            {"id": name}
            for name in (
                "otdp",
                "registry",
                "execution",
                "interface",
                "plugin-ui",
                "plugin-ui-preview",
            )
        ]
        (tmp_path / "standards-lock.json").write_text(
            json.dumps({"standards": lock_ids}), encoding="utf-8"
        )
        monkeypatch.setattr(counter, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(counter, "SOURCE_ROOTS", roots)
        return counter

    def _unreadable(self, monkeypatch, *closed: Path) -> None:
        """Make directories unreadable at the os.scandir boundary — the
        exact boundary os.walk's onerror fires at — on EVERY OS: chmod(0)
        does not remove list permission on Windows (the first PR #95 run
        reddened exactly there: os.walk entered the chmod-0 directory and
        scanned it), so the arms inject PermissionError where the walk
        would meet it instead. pathlib's rglob suppresses the SAME error
        at the same boundary — which is the base's silent narrowing."""
        import os as _os

        real_scandir = _os.scandir
        closed_set = {str(path.resolve()) for path in closed}

        def scandir(path=".", *args, **kwargs):
            resolved = _os.path.realpath(_os.fspath(path))
            if resolved in closed_set or str(_os.fspath(path)) in closed_set:
                raise PermissionError(13, "Permission denied", _os.fspath(path))
            return real_scandir(path, *args, **kwargs)

        monkeypatch.setattr(_os, "scandir", scandir)

    def test_an_unreadable_root_refuses_instead_of_narrowing(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        readable = tmp_path / "src" / "readable"
        readable.mkdir(parents=True)
        (readable / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
        unreadable = tmp_path / "closed-root"
        unreadable.mkdir()
        (unreadable / "secret.py").write_text("PIN = '1.2.3'\n", encoding="utf-8")
        self._unreadable(monkeypatch, unreadable)
        counter = self._armed_counter(tmp_path, monkeypatch, (readable, unreadable))
        code = counter.main([])
        captured = capsys.readouterr()
        assert code == 1
        assert "source tree unreadable" in captured.err

    def test_an_unreadable_subdirectory_refuses_too(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        """The walk-level guard, not only the root: a closed subdirectory
        under a readable root is a refusal, never a silently skipped
        branch of the tree."""
        root = tmp_path / "src" / "root"
        (root / "closed").mkdir(parents=True)
        (root / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "closed" / "secret.py").write_text("PIN = '1.2.3'\n", encoding="utf-8")
        self._unreadable(monkeypatch, root / "closed")
        counter = self._armed_counter(tmp_path, monkeypatch, (root,))
        code = counter.main([])
        captured = capsys.readouterr()
        assert code == 1
        assert "source tree unreadable" in captured.err
