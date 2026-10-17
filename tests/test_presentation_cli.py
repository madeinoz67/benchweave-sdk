"""SDK UI scaffolding remains optional and operates without device access."""

import errno
import importlib
import json
import shutil
from pathlib import Path

import pytest

from benchweave_sdk import cli, presentation, scaffold


def _symlink_or_skip(link: Path, target: Path) -> None:
    """Not main-side: a Windows host without symlink privilege skips instead of failing."""
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")


def run(monkeypatch: pytest.MonkeyPatch, *arguments: str | Path) -> int:
    exit_code: int = cli.main([*map(str, arguments)])
    return exit_code


def check(monkeypatch: pytest.MonkeyPatch, package: Path, **options: str) -> int:
    arguments: list[str | Path] = [
        "check-ui",
        package / "presentation.json",
        "--descriptor",
        package / "descriptor.json",
        "--resources",
        package,
        "--catalogue",
        package / "binding-catalogue.json",
    ]
    for key, value in options.items():
        arguments.extend(["--" + key, value])
    return run(monkeypatch, *arguments)


def test_scaffold_rejects_shadowing_package_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("benchweave_sdk", "benchweave", "os"):
        assert run(monkeypatch, "new", tmp_path / f"p-{name}", "--package", name) == 1


def test_create_ui_resources_is_atomic_on_unusable_descriptors(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    scaffold.create_project(empty, "example_plugin")
    descriptor_path = empty / "src/example_plugin/descriptor.json"
    document = json.loads(descriptor_path.read_bytes())
    document["parameters"] = []
    descriptor_path.write_text(json.dumps(document), encoding="utf-8")
    package = empty / "src/example_plugin"
    with pytest.raises(ValueError, match="at least one readable"):
        presentation.create_ui_resources(empty, "example_plugin")
    assert not (package / "presentation.json").exists()
    assert not (package / "ui").exists()

    unknown = tmp_path / "unknown"
    scaffold.create_project(unknown, "example_plugin")
    descriptor_path = unknown / "src/example_plugin/descriptor.json"
    document = json.loads(descriptor_path.read_bytes())
    document["parameters"][0]["type"] = "float8"
    descriptor_path.write_text(json.dumps(document), encoding="utf-8")
    package = unknown / "src/example_plugin"
    with pytest.raises(ValueError, match="preview_unsupported_parameter_type"):
        presentation.create_ui_resources(unknown, "example_plugin")
    assert not (package / "presentation.json").exists()


def test_optional_ui_preserves_descriptor_and_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plain = tmp_path / "plain"
    ui = tmp_path / "ui"
    run(monkeypatch, "new", plain)
    run(monkeypatch, "new", ui, "--with-ui")
    base = plain / "src/example_plugin"
    package = ui / "src/example_plugin"
    assert (base / "descriptor.json").read_bytes() == (
        package / "descriptor.json"
    ).read_bytes()
    # Issue #394: the --with-ui starter's protocol/adapter carry the drain
    # idiom over its send_receive script, so those two arms differ by that
    # addition; the codec surfaces the generated tests script (transaction
    # and the parsers) are unchanged in both arms, and the base arm stays
    # the plain starter (byte-pinned separately by the scaffold fixture).
    base_protocol = (base / "protocol.py").read_text()
    ui_protocol = (package / "protocol.py").read_text()
    for surface in ("def transaction(verb):", "def parse_identity(raw):",
                    "def parse_voltage(raw):"):
        assert surface in base_protocol and surface in ui_protocol
    assert "def drain(" in ui_protocol and "def drain(" not in base_protocol
    ui_adapter = (package / "adapter.py").read_text()
    assert "await drain(self.services, context)" in ui_adapter
    assert "drain" not in (base / "adapter.py").read_text()
    assert not (base / "presentation.json").exists()
    assert (package / "ui/manifest.json").is_file()
    check(monkeypatch, package, firmware="1.0.0")
    assert "not admission or approval" in capsys.readouterr().out


def test_ui_scaffold_includes_valid_preview_fixtures_and_conformance_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(monkeypatch, "new", tmp_path / "ui", "--with-ui")
    project = tmp_path / "ui"
    package = project / "src/example_plugin"
    assert (package / "ui/fixtures/normal.json").is_file()
    assert (package / "ui/fixtures/warning.json").is_file()
    conformance = project / "tests/test_presentation_preview.py"
    assert conformance.is_file()
    assert "BASELINE_IDS" in conformance.read_text()

    from benchweave_sdk.fixtures import build_preview_model
    from benchweave_sdk.presentation import load_validated_preview_inputs

    candidate = load_validated_preview_inputs(
        package / "presentation.json",
        package / "descriptor.json",
        package,
        package / "binding-catalogue.json",
        firmware=None,
        features=frozenset(),
        panels=frozenset(),
    )
    ids = {scenario.id for scenario in build_preview_model(candidate).scenarios}
    mandatory = {
        "normal",
        "warning",
        "loading",
        "stale",
        "disconnected",
        "critical",
        "trip",
        "recovery",
        "request-rejected",
    }
    assert mandatory <= ids


def test_ui_check_rejects_modified_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(monkeypatch, "new", tmp_path / "ui", "--with-ui")
    package = tmp_path / "ui/src/example_plugin"
    manifest = package / "ui/manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    assert check(monkeypatch, package) == 1


def test_ui_check_rejects_symlinked_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(monkeypatch, "new", tmp_path / "ui", "--with-ui")
    package = tmp_path / "ui/src/example_plugin"
    manifest = package / "ui/manifest.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(manifest.read_bytes())
    manifest.unlink()
    try:
        manifest.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")
    assert check(monkeypatch, package) == 1


def test_ui_check_rejects_resource_root_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(monkeypatch, "new", tmp_path / "ui", "--with-ui")
    package = tmp_path / "ui/src/example_plugin"
    envelope = package / "presentation.json"
    document = json.loads(envelope.read_bytes())
    document["resource_root"] = "../outside"
    envelope.write_text(json.dumps(document))
    assert check(monkeypatch, package) == 1


def test_scaffold_hint_pair_validates_identically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Metric 1's fourth pair: the scaffold-generated example with an
    author-added hinted plot vs its unhinted twin, both feature conditions.

    The scaffold emits no plots, so the author-side step mirrors what a plugin
    developer does: add a receipt-time variable to the catalogue target and a
    time-series plot to the manifest. check-ui must accept both members
    identically (P1/P2) — and the scaffold must declare the ACTIVE contract
    version or this fails before hints are even considered.
    """
    hashlib = importlib.import_module("hashlib")
    presentation = importlib.import_module("benchweave_sdk.presentation")
    scaffold = importlib.import_module("benchweave_sdk.scaffold")

    def authored(hints: list[dict[str, object]] | None) -> Path:
        project = tmp_path / ("ui-hinted" if hints is not None else "ui-plain")
        scaffold.create_project(project, "example_plugin")
        presentation.create_ui_resources(project, "example_plugin")
        package = project / "src/example_plugin"
        if hints is None:
            manifest_path = package / "ui/manifest.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest["pages"][0]["plots"][0].pop("channel_hints", None)
            manifest_raw = json.dumps(manifest, indent=2) + "\n"
            # Bytes, not text: the envelope pins these exact bytes, and text mode
            # on Windows would store CRLF (the main-side original writes text).
            manifest_path.write_bytes(manifest_raw.encode())
            envelope_path = package / "presentation.json"
            envelope = json.loads(envelope_path.read_bytes())
            envelope["manifest"]["sha256"] = hashlib.sha256(manifest_raw.encode()).hexdigest()
            envelope_path.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
        return package

    plain = authored(None)
    hinted = authored([{"variable_id": "value", "color_role": "muted"}])
    assert check(monkeypatch, plain, firmware="1.0.0") == 0
    # No --feature flag is the empty supported-feature host; one flag is the
    # feature-declaring host. Both must accept the hinted twin identically.
    assert check(monkeypatch, hinted, firmware="1.0.0") == 0
    assert check(monkeypatch, hinted, firmware="1.0.0", feature="legend/1.0.0") == 0


def test_new_with_ui_succeeds_under_symlinked_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    _symlink_or_skip(link, real)
    assert run(monkeypatch, "new", link / "proj", "--with-ui") == 0
    package = real / "proj/src/example_plugin"
    for name in (
        "presentation.json",
        "binding-catalogue.json",
        "ui/manifest.json",
        "ui/fixtures/normal.json",
    ):
        assert (package / name).is_file()
    assert (real / "proj/UI-GUIDE.md").is_file()
    assert (real / "proj/tests/test_presentation_preview.py").is_file()

    # SRF-1 control: the same package scaffolded through a canonical path must
    # be byte-identical — the fix changes where writes happen, never what.
    control = tmp_path / "control"
    assert run(monkeypatch, "new", control, "--with-ui") == 0
    generated = sorted(
        path.relative_to(real / "proj") for path in (real / "proj").rglob("*") if path.is_file()
    )
    assert generated == sorted(
        path.relative_to(control) for path in control.rglob("*") if path.is_file()
    )
    for relative in generated:
        assert (real / "proj" / relative).read_bytes() == (control / relative).read_bytes()


def test_check_ui_refuses_symlinked_ancestor_with_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run(monkeypatch, "new", tmp_path / "real", "--with-ui")
    link = tmp_path / "link"
    _symlink_or_skip(link, tmp_path / "real")
    assert check(monkeypatch, link / "src/example_plugin") == 1
    assert "path_symlink_component:" in capsys.readouterr().err


def test_read_file_propagates_genuine_not_directory(tmp_path: Path) -> None:
    presentation = importlib.import_module("benchweave_sdk.presentation")
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"regular file\n")
    with pytest.raises(OSError) as details:
        presentation.read_file(blocker / "descriptor.json")
    assert details.value.errno == errno.ENOTDIR
    assert "path_symlink_component" not in str(details.value)


# --- Added here, not main-side: the two cases above them assert exit 1 only. ---


def test_resource_root_escape_is_refused_before_anything_outside_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """What the guard guarantees is that nothing outside --resources is read; record the reads.

    test_ui_check_rejects_resource_root_escape asserts exit 1 only, and exit 1
    is also what the envelope schema gives a ``..`` root on its own. So this
    case plants a real manifest where the escape points, records every
    ``read_file`` call, and asserts none of them left the resources root. With
    the guard deleted the planted manifest is read before validation refuses.
    """
    run(monkeypatch, "new", tmp_path / "ui", "--with-ui")
    package = tmp_path / "ui/src/example_plugin"
    outside = package.parent / "outside"
    shutil.copytree(package / "ui", outside)
    envelope = package / "presentation.json"
    document = json.loads(envelope.read_bytes())
    document["resource_root"] = "../outside"
    envelope.write_text(json.dumps(document))

    reads: list[Path] = []
    real_read = presentation.read_file

    def recording_read(path: Path, limit: int = 262144) -> bytes:
        reads.append(Path(path))
        return real_read(path, limit)

    monkeypatch.setattr(presentation, "read_file", recording_read)
    capsys.readouterr()
    assert check(monkeypatch, package) == 1
    assert "Unsafe presentation resource path" in capsys.readouterr().err
    escaped = [path for path in reads if path.resolve().is_relative_to(outside.resolve())]
    assert escaped == [], "nothing outside the resources root may be read"


def test_symlinked_resource_is_refused_as_a_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 1 alone is also what a missing or non-regular file gives; name the refusal."""
    run(monkeypatch, "new", tmp_path / "ui", "--with-ui")
    package = tmp_path / "ui/src/example_plugin"
    manifest = package / "ui/manifest.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(manifest.read_bytes())
    manifest.unlink()
    try:
        manifest.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable (privilege or filesystem)")
    capsys.readouterr()
    assert check(monkeypatch, package) == 1
    assert "path_symlink_component: " in capsys.readouterr().err


def test_overdeep_descriptor_is_a_finding_not_a_bare_document_error() -> None:
    """RedTeam PT-7 E4: a malformed/over-deep DESCRIPTOR leaked the reader's
    bare "Document nesting limit exceeded" while the same fault in the preset
    is a typed limit_exceeded finding — the descriptor side now matches the
    preset side's typing (a findings report, path "descriptor")."""
    deep = b'{"a": ' + b"[" * 1000 + b"]" * 1000 + b"}"
    report = presentation.validate_preset(
        b"{}", descriptor_raw=deep, settings_schema_raw=b"{}", firmware="1.0"
    )
    assert report.valid is False
    assert [(f.code, f.path) for f in report.findings] == [("limit_exceeded", "descriptor")]


def test_overdeep_descriptor_in_resolve_preset_action_is_typed() -> None:
    """The resolver cannot return a report; its descriptor read faults surface
    as a typed, code-carrying ValueError instead of a bare DocumentError."""
    deep = b'{"a": ' + b"[" * 1000 + b"]" * 1000 + b"}"
    with pytest.raises(ValueError, match="descriptor_document_limit_exceeded:"):
        presentation.resolve_preset_action(b"{}", descriptor_raw=deep)


# --- issue #444: the commissioned policy's firmware authority -------------------

_SETPOINT = (
    Path(__file__).resolve().parent / "fixtures" / "setpoint_plugin" / "src" / "setpoint_demo"
)
_INCOMPATIBLE = (
    "incompatible_firmware",
    "preset.supported_firmware",
    "A known firmware compatible with the descriptor and preset is required",
)


def _report(descriptor_identity: dict, firmware: str | None):
    """Validate the fixture preset against a rebound descriptor identity."""
    descriptor = json.loads((_SETPOINT / "descriptor.json").read_bytes())
    descriptor["identity"] = descriptor_identity
    report = presentation.validate_preset(
        (_SETPOINT / "config/presets/steady.json").read_bytes(),
        descriptor_raw=json.dumps(descriptor).encode(),
        settings_schema_raw=(_SETPOINT / "config/settings.schema.json").read_bytes(),
        firmware=firmware,
    )
    return report


def test_commissioned_policy_admits_missing_firmware() -> None:
    """The corpus's commissioned pattern (policy commissioned, no
    descriptor-side firmware list): a missing firmware value is the honest
    offline posture — the bench's commissioned record is the authority and
    the apply-time established-firmware gate governs."""
    report = _report(
        {
            "strategy": "adapter",
            "manufacturer": "BenchWeave Labs",
            "model": "setpoint-demo",
            "firmware_policy": "commissioned",
        },
        None,
    )
    assert report.valid, report.findings


def test_commissioned_policy_admits_preset_listed_firmware() -> None:
    report = _report(
        {
            "strategy": "adapter",
            "manufacturer": "BenchWeave Labs",
            "model": "setpoint-demo",
            "firmware_policy": "commissioned",
        },
        "1.0.0",
    )
    assert report.valid, report.findings


def test_commissioned_preset_list_mismatch_refuses() -> None:
    """Negative control C3: the preset's own declared applicability list
    keeps full force regardless of policy."""
    report = _report(
        {
            "strategy": "adapter",
            "manufacturer": "BenchWeave Labs",
            "model": "setpoint-demo",
            "firmware_policy": "commissioned",
        },
        "2.0.0",
    )
    assert [(f.code, f.path, f.message) for f in report.findings] == [_INCOMPATIBLE]


def test_commissioned_declared_list_still_enforced_for_missing() -> None:
    """Rule 3: a descriptor-DECLARED firmware list is enforced regardless of
    policy — None is not a member."""
    report = _report(
        {
            "strategy": "adapter",
            "manufacturer": "BenchWeave Labs",
            "model": "setpoint-demo",
            "firmware_policy": "commissioned",
            "supported_firmware": ["1.0.0"],
        },
        None,
    )
    assert [(f.code, f.path, f.message) for f in report.findings] == [_INCOMPATIBLE]


def test_listed_policy_missing_firmware_refuses() -> None:
    """Negative control C4: unknown firmware still fails under listed
    policy."""
    report = _report(
        {
            "strategy": "adapter",
            "manufacturer": "BenchWeave Labs",
            "model": "setpoint-demo",
            "firmware_policy": "listed",
            "supported_firmware": ["1.0.0"],
        },
        None,
    )
    assert [(f.code, f.path, f.message) for f in report.findings] == [_INCOMPATIBLE]


# --- issue #463 row 7: check-preset --firmware reaches the #444 postures -------

_COMMISSIONED_IDENTITY = {
    "strategy": "adapter",
    "manufacturer": "BenchWeave Labs",
    "model": "setpoint-demo",
    "firmware_policy": "commissioned",
}
_LISTED_IDENTITY = {
    "strategy": "adapter",
    "manufacturer": "BenchWeave Labs",
    "model": "setpoint-demo",
    "firmware_policy": "listed",
    "supported_firmware": ["1.0.0"],
}


def _check_preset_arguments(
    tmp_path: Path, identity: dict, *extra: str
) -> list[str | Path]:
    """Materialise a descriptor with the given identity (the #444 pairs, on
    disk for the CLI surface) and build the check-preset argv for the fixture
    preset and settings schema."""
    descriptor = json.loads((_SETPOINT / "descriptor.json").read_bytes())
    descriptor["identity"] = identity
    descriptor_path = tmp_path / "descriptor.json"
    descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
    return [
        "check-preset",
        _SETPOINT / "config/presets/steady.json",
        "--descriptor",
        descriptor_path,
        "--settings-schema",
        _SETPOINT / "config/settings.schema.json",
        *extra,
    ]


def test_check_preset_omitted_firmware_commissioned_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--firmware omitted under commissioned policy is the #444 honest
    offline input: the CLI runs the validation and passes (exit 0), it does
    not refuse the invocation as a usage error (row 7's flag burden)."""
    arguments = _check_preset_arguments(tmp_path, _COMMISSIONED_IDENTITY)
    assert run(monkeypatch, *arguments) == 0
    assert "Offline presentation checks passed" in capsys.readouterr().out


def test_check_preset_omitted_firmware_listed_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same omission under listed policy is a finding, not a usage error:
    the gate cannot decide compatibility offline, so the validation runs and
    refuses with incompatible_firmware."""
    arguments = _check_preset_arguments(tmp_path, _LISTED_IDENTITY)
    assert run(monkeypatch, *arguments) == 1
    rendered = capsys.readouterr()
    assert (
        f"{_INCOMPATIBLE[0]}: {_INCOMPATIBLE[1]}: {_INCOMPATIBLE[2]}\n" in rendered.out
    )
    assert "Presentation validation failed." in rendered.err


@pytest.mark.parametrize(
    ("identity", "firmware", "expected"),
    [
        (_COMMISSIONED_IDENTITY, "1.0.0", 0),
        (_COMMISSIONED_IDENTITY, "2.0.0", 1),
        (_LISTED_IDENTITY, "1.0.0", 0),
        (_LISTED_IDENTITY, "2.0.0", 1),
    ],
    ids=[
        "commissioned-compatible",
        "commissioned-mismatch",
        "listed-compatible",
        "listed-mismatch",
    ],
)
def test_check_preset_supplied_firmware_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    identity: dict,
    firmware: str,
    expected: int,
) -> None:
    """AR-4: with --firmware supplied, exit code and rendered output are
    identical for both policies — the option's optionality is the only
    behaviour change."""
    arguments = _check_preset_arguments(tmp_path, identity, "--firmware", firmware)
    assert run(monkeypatch, *arguments) == expected
    rendered = capsys.readouterr()
    if expected == 0:
        assert "Offline presentation checks passed" in rendered.out
        assert "incompatible_firmware" not in rendered.out
    else:
        assert (
            f"{_INCOMPATIBLE[0]}: {_INCOMPATIBLE[1]}: {_INCOMPATIBLE[2]}\n"
            in rendered.out
        )
        assert "Presentation validation failed." in rendered.err


def test_check_preset_settings_schema_stays_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AR-3: --settings-schema keeps its usage-error refusal — a URN-pinned
    schema reference carries no path, so there is nothing sound to default
    (design §4.3)."""
    descriptor = json.loads((_SETPOINT / "descriptor.json").read_bytes())
    descriptor_path = tmp_path / "descriptor.json"
    descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
    exit_code = run(
        monkeypatch,
        "check-preset",
        _SETPOINT / "config/presets/steady.json",
        "--descriptor",
        descriptor_path,
    )
    assert exit_code == 2
    assert "Missing option '--settings-schema'." in capsys.readouterr().err


# --- issue #460 §4: check-ui points unsupported_version findings at migrate-ui ---


def test_check_ui_points_unsupported_version_at_migrate_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The remediation line rides the findings, names the concrete command
    shape, and fires ONLY on unsupported_version over the three contract
    documents — a digest_mismatch (hand-corrupted bytes at the right version)
    is a different failure with a different remedy."""
    from test_migrate_ui import _coherent_stale

    stale = _coherent_stale(tmp_path / "stale")
    capsys.readouterr()
    assert check(monkeypatch, stale) == 1
    rendered = capsys.readouterr().out
    assert "benchweave-sdk migrate-ui" in rendered, rendered
    assert "--resources" in rendered
    assert "--catalogue" in rendered

    # A fresh project hears nothing about migration.
    run(monkeypatch, "new", tmp_path / "fresh", "--with-ui")
    fresh = tmp_path / "fresh/src/example_plugin"
    capsys.readouterr()
    assert check(monkeypatch, fresh) == 0
    assert "migrate-ui" not in capsys.readouterr().out

    # A digest_mismatch is not version staleness: no remediation line. (The
    # corrupted manifest must live on the AT-ACTIVE project — on the stale
    # one the envelope's version gate rejects first and the finding stays
    # unsupported_version.)
    manifest = fresh / "ui/manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    capsys.readouterr()
    assert check(monkeypatch, fresh) == 1
    rendered = capsys.readouterr().out
    assert "digest_mismatch" in rendered, rendered
    assert "migrate-ui" not in rendered


# --- issue #463 row 8 (L10): the regen-fixtures command ------------------------


def _stale_the_examples(package: Path) -> None:
    """Rename the observation targets in the catalogue, leaving the scaffolded
    example fixtures speaking the old binding ids — the axis-A state the
    command exists to repair."""
    catalogue = json.loads((package / "binding-catalogue.json").read_bytes())
    for target in catalogue["targets"]:
        target["id"] = f"renamed-{target['id']}"
        target["parameter_id"] = f"renamed-{target['parameter_id']}"
    (package / "binding-catalogue.json").write_text(
        json.dumps(catalogue), encoding="utf-8"
    )


def test_regen_fixtures_cli_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AR-L10-2 arm 1: after a catalogue edit the command exits 0, names both
    written files, and carries the standing offline disclaimer."""
    project = tmp_path / "project"
    run(monkeypatch, "new", project, "--with-ui")
    package = project / "src/example_plugin"
    _stale_the_examples(package)
    capsys.readouterr()

    assert run(monkeypatch, "regen-fixtures", project) == 0

    rendered = capsys.readouterr().out
    assert "normal.json" in rendered, rendered
    assert "warning.json" in rendered, rendered
    assert "not admission" in rendered, rendered


def test_regen_fixtures_cli_refuses_author_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AR-L10-2 arm 2: author content at an example filename is exit 1 with
    the `regen_fixtures_author_content:` prefix — never an overwrite."""
    project = tmp_path / "project"
    run(monkeypatch, "new", project, "--with-ui")
    package = project / "src/example_plugin"
    authored = json.loads((package / "ui/fixtures/normal.json").read_bytes())
    authored["id"] = "custom"
    (package / "ui/fixtures/normal.json").write_text(
        json.dumps(authored), encoding="utf-8"
    )
    capsys.readouterr()

    assert run(monkeypatch, "regen-fixtures", project) == 1

    captured = capsys.readouterr()
    assert "regen_fixtures_author_content:" in captured.err
    assert json.loads((package / "ui/fixtures/normal.json").read_bytes())["id"] == "custom"


def test_regen_fixtures_cli_unknown_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AR-L10-2 arm 3: a project path that does not exist is a usage error
    (exit 2, the Path(exists=True) family). The stderr assertion pins WHICH
    usage error — on main this arm's exit code alone is green by coincidence
    ("No such command" also exits 2), so the arm names the path refusal to
    stay a real check."""
    capsys.readouterr()
    assert run(monkeypatch, "regen-fixtures", tmp_path / "missing") == 2
    captured = capsys.readouterr()
    assert "No such command" not in captured.err, captured.err
    assert "does not exist" in captured.err, captured.err
