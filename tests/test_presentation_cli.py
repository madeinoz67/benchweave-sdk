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
    for name in ("descriptor.json", "adapter.py", "protocol.py"):
        assert (base / name).read_bytes() == (package / name).read_bytes()
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
        catalogue_path = package / "binding-catalogue.json"
        catalogue = json.loads(catalogue_path.read_bytes())
        catalogue["targets"][0]["variables"].insert(
            0,
            {
                "id": "time",
                "type": "number",
                "unit": "s",
                "shape": "scalar",
                "axis_role": "receipt_time",
            },
        )
        catalogue_path.write_text(json.dumps(catalogue, indent=2) + "\n", encoding="utf-8")
        manifest_path = package / "ui/manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        plot: dict[str, object] = {
            "kind": "time_series",
            "binding_id": manifest["bindings"][0]["id"],
            "x": "time",
            "y": ["value"],
        }
        if hints is not None:
            plot["channel_hints"] = hints
        manifest["pages"][0]["plots"] = [plot]
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
