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


def _copy_prose_surfaces(scratch: Path) -> None:
    """The bare gate's second scope (issue #412): the prose surfaces must
    ride every scratch tree the battery runs the widened bare command
    over — a scratch tree without them refuses on the missing surface,
    which is the counter's fail-closed posture working, not a defect."""
    shutil.copytree(REPO / "website", scratch / "website")
    shutil.copytree(REPO / "user_guide", scratch / "user_guide")
    shutil.copy(REPO / "README.md", scratch / "README.md")
    shutil.copy(REPO / "index.qmd", scratch / "index.qmd")
    shutil.copy(REPO / "great-docs.yml", scratch / "great-docs.yml")


def _prose_scratch(tmp_path: Path) -> Path:
    """A scratch repo carrying the FULL file set the bare gate needs (the
    #412 INCONCLUSIVE branch's requirement): both source roots, the lock,
    the counter, the prose surfaces and the derivation source."""
    scratch = tmp_path / "scratch-prose-repo"
    shutil.copytree(REPO / "src/benchweave_sdk", scratch / "src/benchweave_sdk")
    shutil.copytree(
        REPO / "src/benchweave_sdk_server", scratch / "src/benchweave_sdk_server"
    )
    (scratch / "scripts").mkdir(parents=True)
    shutil.copy(COUNTER, scratch / "scripts/count_version_literals.py")
    shutil.copy(REPO / "standards-lock.json", scratch / "standards-lock.json")
    _copy_prose_surfaces(scratch)
    return scratch


def _prose_counter_at(scratch: Path):
    """Load the counter COPY inside the scratch repo — its REPO_ROOT
    (and therefore both scan scopes) resolves to the scratch tree."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "prose_counter_under_test", scratch / "scripts/count_version_literals.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prose_run(scratch: Path, capsys, argv: list[str] | None = None):
    counter = _prose_counter_at(scratch)
    code = counter.main(argv or [])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


class TestScaffoldDerivation:
    """The example descriptor's pin is derived (§1.4). Since WS2 the
    descriptor is template output, so the derivation is pinned through the
    R-2 fixture's rendered bytes (byte-identical to create_project output)."""

    def _rendered_descriptor(self) -> dict[str, object]:
        path = (
            REPO
            / "tests/fixtures/scaffold_expected/base/src/example_plugin/descriptor.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def test_example_descriptor_pins_the_lock_active_version(self) -> None:
        assert self._rendered_descriptor()["otdp_version"] == active_version("otdp")

    def test_example_descriptor_validates(self) -> None:
        """The scaffold generates what the SDK validates today (validation
        itself resolves the active schema — the parity the slice pins)."""
        validate_descriptor(self._rendered_descriptor())  # type: ignore[arg-type]


class TestGeneratedDocumentDerivations:
    """The example fixture (fixtures.py since #463 row 8) ×2 + the generated plugin-ui set."""

    def test_preview_fixture_carries_the_lock_active_version(self) -> None:
        from benchweave_sdk.fixtures import _preview_fixture

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

        from benchweave_sdk.fixtures import _preview_fixture

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
        pinned (36 at main after the #347 WS2/WS3 scaffold merges; I2c adds
        events.py and jsonpatch.py, the 37th and 38th files; I3a adds
        serial.py, the 39th; #308 deletes preview_server.py and
        preview_tui.py back to 37; I3b adds library.py, the 38th; #385
        adds binding.py and I3c adds retention.py, the 39th and 40th; the
        #422 inc1 env-file autoload adds env_file.py, the 41st; I4a adds
        analysis.py and report.py, the 42nd and 43rd; the #422 inc3
        lifecycle twins add lifecycle.py, the 44th; #440 adds shim.py,
        the 45th) —
        a scope change is a visible diff, never a silent denominator move.
        The server half is issue #309 slice A's scope extension: deleting
        the tree or narrowing the roots reds here."""
        result = subprocess.run(
            [sys.executable, str(COUNTER), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["scanned"] == 48, (

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
        _copy_prose_surfaces(scratch)
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
        _copy_prose_surfaces(scratch)
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
        _copy_prose_surfaces(scratch)
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
        visible register edit — a planted literal inside publishing.py fails
        the expectation, never the count."""
        scratch = tmp_path / "scratch-repo"
        (scratch / "scripts").mkdir(parents=True)
        shutil.copy(COUNTER, scratch / "scripts/count_version_literals.py")
        shutil.copy(REPO / "standards-lock.json", scratch / "standards-lock.json")
        shutil.copytree(REPO / "src/benchweave_sdk", scratch / "src/benchweave_sdk")
        shutil.copytree(
            REPO / "src/benchweave_sdk_server", scratch / "src/benchweave_sdk_server"
        )
        _copy_prose_surfaces(scratch)
        registered = scratch / "src/benchweave_sdk/publishing.py"
        registered.write_bytes(
            registered.read_bytes() + b'\n_PLANT = "9.9.9"\n',  # noqa: E501
        )
        result = subprocess.run(
            [sys.executable, str(scratch / "scripts/count_version_literals.py")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "register expectation failed: src/benchweave_sdk/publishing.py" in result.stdout
        assert "expects 3 literals, found 4" in result.stdout


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
        _copy_prose_surfaces(scratch)
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
            "plugin-ui-class-reference",
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
        """Fold row 6: the publishing register pins the VALUES — a
        semantics-changing substitution (MANIFEST_SCHEMA_VERSION 0.1.1 ->
        9.9.9) fails at unchanged cardinality."""
        scratch = self._scratch_sdk_repo(tmp_path)
        publishing = scratch / "src/benchweave_sdk/publishing.py"
        text = publishing.read_text(encoding="utf-8")
        old = '"0.1.1"'
        assert old in text
        publishing.write_text(text.replace(old, '"9.9.9"'), encoding="utf-8")
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
            "src/benchweave_sdk/publishing.py",
            "src/benchweave_sdk/registry_ops.py",
        }
        contracts = register["src/benchweave_sdk/standards/plugin-ui/contracts.py"]
        assert contracts[1] == 3
        assert contracts[2] is None  # digest-pinned whole, no value pin
        publishing = register["src/benchweave_sdk/publishing.py"]
        assert publishing[1] == 3
        assert publishing[2] == ("0.1.1", "0.0.0", "0.1.0")
        registry_ops = register["src/benchweave_sdk/registry_ops.py"]
        assert registry_ops[1] == 1
        assert registry_ops[2] == ("1.1.0",)

    def test_a_register_edit_is_detected_by_the_pin(self, tmp_path: Path) -> None:
        """The pin's teeth: a scratch copy with the publishing expectation
        loosened (3 -> 4) fails the same comparison the committed pin
        makes."""
        scratch = tmp_path / "twin-register-edited.py"
        text = COUNTER.read_text(encoding="utf-8")
        edited = text.replace('3,\n        ("0.1.1"', '4,\n        ("0.1.1"')
        assert edited != text, "the mutation arm's needle vanished from the twin"
        scratch.write_text(edited, encoding="utf-8")
        register = self._counter_register(scratch)
        with pytest.raises(AssertionError):
            assert register["src/benchweave_sdk/publishing.py"][1] == 3

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
                "plugin-ui-class-reference",
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


class TestProseScope:
    """The prose scan class over the release-managed prose surfaces (issue
    #412, design record 2026-10-19 in ``.claude/deep-review/``): every file
    under ``website/``, ``README.md``, ``index.qmd`` and every ``*.qmd``
    under ``user_guide/``, gated by per-file site pins, a pinned
    scanned-file census, and a DERIVED ``website/index.html`` expectation
    (``2 x releases + static`` from ``great-docs.yml``'s versions map).

    The arms load the SCRATCH copy of the counter and call ``main``
    directly (the in-file precedent of TestUnreadableRootRefuses) — the
    CLI exit contract IS ``main``'s return value (``raise SystemExit(
    main())``), so the exit statuses asserted here are the bare
    command's, without a fresh OS process per arm.
    """

    PROSE_SURFACES = ("website", "user_guide", "README.md", "index.qmd", "great-docs.yml")

    def _scratch_prose_repo(self, tmp_path: Path) -> Path:
        return _prose_scratch(tmp_path)

    def _counter_at(self, scratch: Path):
        return _prose_counter_at(scratch)

    def _run(self, scratch: Path, capsys, argv: list[str] | None = None):
        return _prose_run(scratch, capsys, argv)

    def test_a_planted_new_prose_file_refuses(self, tmp_path: Path, capsys) -> None:
        """The issue's shape 1: a version claim on a NEW file under
        website/ — caught by the unregistered-literal row AND the file
        census (a new file reds even before it carries a literal)."""
        scratch = self._scratch_prose_repo(tmp_path)
        (scratch / "website/upgrade-guide.html").write_text(
            "Requires SDK 0.7.1 or later.\n", encoding="utf-8"
        )
        code, out = self._run(scratch, capsys)
        assert code == 1, out
        assert "unregistered prose literal: website/upgrade-guide.html:1" in out
        assert "prose census failed" in out

    def test_a_planted_sentence_inside_the_index_hero_refuses(
        self, tmp_path: Path, capsys
    ) -> None:
        """The issue's shape 2: an unpatterned sentence added inside a
        REGISTERED-DERIVED file — the derived expectation moves and every
        site of the mismatched file is listed unregistered (the gate
        cannot know WHICH site is new; naming all of them is the
        non-fabricating report)."""
        scratch = self._scratch_prose_repo(tmp_path)
        index = scratch / "website/index.html"
        lines = index.read_text(encoding="utf-8").splitlines()
        marker = next(i for i, line in enumerate(lines) if "Python 3.13+" in line)
        lines.insert(marker + 1, '<div class="status-line">Works with SDK 0.7.1 gateways.</div>')
        index.write_text("\n".join(lines) + "\n", encoding="utf-8")
        code, out = self._run(scratch, capsys)
        assert code == 1, out
        assert f"website/index.html:{marker + 2}" in out
        assert "unregistered prose literal" in out

    def test_clean_head_holds(self, tmp_path: Path, capsys) -> None:
        """The clean tree passes BOTH legs — the register pins, the
        census and the derivation all hold on the committed state."""
        scratch = self._scratch_prose_repo(tmp_path)
        code, out = self._run(scratch, capsys)
        assert code == 0, out
        assert "sdk prose version literals: 0 outside register" in out

    def test_a_removed_registered_site_reds(self, tmp_path: Path, capsys) -> None:
        """Shrinkage has teeth too: the pins are exact, so REMOVING a
        registered site (the getting-started firmware example) fails the
        expectation exactly as growth does."""
        scratch = self._scratch_prose_repo(tmp_path)
        guide = scratch / "user_guide/getting-started.qmd"
        text = guide.read_text(encoding="utf-8")
        assert "  --firmware 1.0.0\n" in text
        guide.write_text(text.replace("  --firmware 1.0.0\n", ""), encoding="utf-8")
        code, out = self._run(scratch, capsys)
        assert code == 1, out
        assert "prose register expectation failed: user_guide/getting-started.qmd" in out
        assert "expects 1 sites, found 0" in out

    def test_the_derivation_tracks_the_versions_map(self, tmp_path: Path, capsys) -> None:
        """A clean release train never reddens: registering a release
        (one versions-map row + its selector occurrences) moves the
        derived expectation in lockstep — hold. The map row WITHOUT its
        selector occurrences is the loud red (the derivation moved, the
        HTML did not)."""
        scratch = self._scratch_prose_repo(tmp_path)
        yml = scratch / "great-docs.yml"
        yml_text = yml.read_text(encoding="utf-8")
        anchor = "    git_ref: v0.16.0\n"
        assert anchor in yml_text
        fake_row = "  - tag: v9.9.9\n    label: v9.9.9\n    git_ref: v9.9.9\n"
        yml.write_text(yml_text.replace(anchor, anchor + fake_row), encoding="utf-8")
        index = scratch / "website/index.html"
        html_text = index.read_text(encoding="utf-8")
        option_anchor = '<option value="docs/">v0.17.0 (latest)</option>\n'
        assert option_anchor in html_text
        fake_option = '          <option value="docs/v/v9.9.9/">v9.9.9</option>\n'
        index.write_text(
            html_text.replace(option_anchor, option_anchor + fake_option), encoding="utf-8"
        )
        code, out = self._run(scratch, capsys)
        assert code == 0, out
        # The same map row without the selector occurrences reds by the
        # derived number (2 x 24 + 11 = 59).
        index.write_text(html_text, encoding="utf-8")
        code, out = self._run(scratch, capsys)
        assert code == 1, out
        assert "website/index.html expects 59 sites" in out

    def test_the_prose_matcher_is_pinned_to_the_authority_literal(self) -> None:
        """The twin's PATTERN_DOCS is the gateway docs scope's committed
        prose definition, copied VERBATIM — pinned here against the
        literal so a semantic regex change in this copy alone is a
        visible suite diff (the cross-repo drift residual until H1)."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("prose_counter_pinned", COUNTER)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.PATTERN_DOCS.pattern == (
            r"(?<![\w.])(?:[vV])?\d+\.\d+\.\d+(?:-(?:dev|rc|alpha|beta)\d*)?(?!\.\d)"
        )
        # The two boundary behaviors the gateway battery pins on its own
        # copy (IP fragments out, sentence-final period in).
        assert module.PATTERN_DOCS.search("server at 192.168.1.1:8080") is None
        assert module.PATTERN_DOCS.search("active is 0.2.2.") is not None

    def test_the_scanned_file_census_is_pinned(self, tmp_path: Path, capsys) -> None:
        """The denominator is pinned: the file-set census reds on any new
        or removed prose file EVEN WHEN IT CARRIES ZERO LITERALS (the
        issue's shape 1 caught before the plant writes a version), and
        the clean tree scans exactly 11 files."""
        scratch = self._scratch_prose_repo(tmp_path)
        code, out = self._run(scratch, capsys, ["--json"])
        assert code == 0, out
        payload = json.loads(out)
        assert payload["prose"]["scanned"] == 11
        (scratch / "website/empty-page.html").write_text(
            "<html><body>No versions here.</body></html>\n", encoding="utf-8"
        )
        code, out = self._run(scratch, capsys)
        assert code == 1, out
        assert "prose census failed" in out
        assert "website/empty-page.html" in out


class TestProseFoldHardening:
    """The 2026-10-19 fold-wave arms (the adversary lanes' F1-F4; the
    governor's F5 is a records correction, not an arm). Each row landed
    RED-first with its fix in one commit, per the fold instruction — the
    class is separate so TestProseScope stays the design's exactly-7."""

    def test_a_symlinked_directory_under_website_refuses(
        self, tmp_path: Path, capsys
    ) -> None:
        """F1: a directory symlink under website/ escapes BOTH legs — rglob
        never descends it and the link itself fails is_file — so the whole
        subtree is invisible (the adversary's repro: the real directory
        OUTSIDE the scan set, only the link inside). The policy is
        fail-closed: refuse, naming the symlink. POSIX-only arm: symlink
        creation needs privileges on Windows (the #476 F2 lane's skipif
        precedent); the refusal path itself is platform-neutral code."""
        import os

        if os.name == "nt":
            pytest.skip("symlink creation needs privileges on Windows")
        scratch = _prose_scratch(tmp_path)
        site = scratch / "dirsite"  # outside every scanned surface
        site.mkdir()
        (site / "claim.html").write_text("Needs 0.7.1 today.\n", encoding="utf-8")
        (scratch / "website/legacy-docs").symlink_to(site, target_is_directory=True)
        code, out = _prose_run(scratch, capsys)
        assert code == 1, out
        assert "version_literal_count_failed" in out
        assert "website/legacy-docs" in out

    def test_a_markdown_file_under_user_guide_refuses(self, tmp_path: Path, capsys) -> None:
        """F2: user_guide/ coverage was extension-gated (*.qmd), so a
        renamed page escapes the scan and the census with one edit —
        user_guide/notes.md carrying a stale claim exits 0."""
        scratch = _prose_scratch(tmp_path)
        (scratch / "user_guide/notes.md").write_text(
            "Requires SDK 0.7.1 or later.\n", encoding="utf-8"
        )
        code, out = _prose_run(scratch, capsys)
        assert code == 1, out
        assert "user_guide/notes.md:1" in out
        assert "prose census failed" in out

    def test_an_uppercase_extension_under_user_guide_refuses(
        self, tmp_path: Path, capsys
    ) -> None:
        """F2: the extension gate was also CASE-sensitive on POSIX —
        NOTES.QMD is invisible to rglob('*.qmd') on the very platform
        CI runs it. The directory walk has no case to be wrong about."""
        scratch = _prose_scratch(tmp_path)
        (scratch / "user_guide/NOTES.QMD").write_text(
            "Requires SDK 0.7.1 or later.\n", encoding="utf-8"
        )
        code, out = _prose_run(scratch, capsys)
        assert code == 1, out
        assert "user_guide/NOTES.QMD:1" in out
        assert "prose census failed" in out

    def test_non_utf8_bytes_refuse_with_the_documented_shape(
        self, tmp_path: Path, capsys
    ) -> None:
        """F3: unreadable bytes are a REFUSAL in the documented shape —
        version_literal_count_failed naming the failure — not a raw
        UnicodeDecodeError traceback. The exit code was already 1
        (fail-closed held) but the reader saw the wrong thing."""
        scratch = _prose_scratch(tmp_path)
        (scratch / "website/assets/bad.css").write_bytes(b"/* caf\xe9 */\n")
        code, out = _prose_run(scratch, capsys)
        assert code == 1, out
        assert "version_literal_count_failed" in out

    def test_os_junk_never_reddens_the_census(self, tmp_path: Path, capsys) -> None:
        """F4: local OS noise (.DS_Store, Thumbs.db) is excluded BY NAME
        ONLY — never committed — so it cannot redden the census with an
        unsanctioned file. This is not a general ignore mechanism: a
        file is prose-scanned unless it carries one of these two names."""
        scratch = _prose_scratch(tmp_path)
        (scratch / "website/.DS_Store").touch()
        (scratch / "user_guide/Thumbs.db").touch()
        code, out = _prose_run(scratch, capsys)
        assert code == 0, out
        assert "69 sites, 11 files scanned" in out
