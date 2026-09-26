"""Nothing is read or executed from outside the package unless the root is the gateway checkout.

Each case moves a module's ``__file__`` into a tree shaped like the
submodule mount (``<root>/packages/sdk/src/benchweave_sdk/``), so that
``parents[4]`` is a root the test controls, and removes the vendored copy the
module would normally find.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from benchweave_sdk import fixtures, presentation, validation

REPO = Path(__file__).resolve().parents[1]


def _mount(tmp_path: Path, project_name: str) -> tuple[Path, Path]:
    root = tmp_path / "root"
    package = root / "packages/sdk/src/benchweave_sdk"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{project_name}"\n', encoding="utf-8"
    )
    return root, package


@pytest.fixture
def fresh_caches() -> Iterator[None]:
    validation.contract_documents.cache_clear()
    presentation._contract.cache_clear()
    yield
    validation.contract_documents.cache_clear()
    presentation._contract.cache_clear()


@pytest.mark.usefixtures("fresh_caches")
def test_contract_documents_refuses_a_foreign_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, package = _mount(tmp_path, "somebody-elses-project")
    (root / "standards").mkdir()
    monkeypatch.setattr(validation, "files", lambda _name: package)
    monkeypatch.setattr(validation, "__file__", str(package / "validation.py"))
    with pytest.raises(RuntimeError, match="^SDK standards tree missing"):
        validation.contract_documents()


def _fixture_schema_relative() -> Path:
    from benchweave_sdk.served import active_version

    vendored = REPO / "src/benchweave_sdk/standards/plugin-ui-preview"
    # Multi-version serving (#203 slice 1): two versions are vendored; the
    # fixture schema the loader wants is the ACTIVE one's (its path stays a
    # module literal until slice 7's derivation sweep).
    active = active_version("plugin-ui-preview")
    packaged = vendored / active / "fixture.schema.json"
    return Path("standards/plugin-ui-preview") / active / packaged.name


@pytest.mark.parametrize(
    ("project_name", "trusted"),
    [("benchweave", True), ("somebody-elses-project", False)],
)
def test_fixture_schema_fallback_only_trusts_the_gateway_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_name: str, trusted: bool
) -> None:
    """The schema is present at the fallback path in both cases; only the root's name differs."""
    root, package = _mount(tmp_path, project_name)
    schema = root / _fixture_schema_relative()
    schema.parent.mkdir(parents=True)
    schema.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(fixtures, "__file__", str(package / "fixtures.py"))
    if trusted:
        assert fixtures._schema_path() == schema
    else:
        with pytest.raises(RuntimeError, match="^SDK preview fixture schema missing"):
            fixtures._schema_path()


@pytest.mark.usefixtures("fresh_caches")
def test_presentation_validator_is_never_executed_from_outside_the_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The removed fallback exec_module-ed this exact path; the decoy records if it ever runs."""
    root, package = _mount(tmp_path, "benchweave")
    marker = tmp_path / "executed"
    decoy = root / "src/benchweave/presentation/contracts.py"
    decoy.parent.mkdir(parents=True)
    decoy.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n", encoding="utf-8"
    )
    monkeypatch.setattr(presentation, "__file__", str(package / "presentation.py"))
    with pytest.raises(RuntimeError, match="^SDK presentation validator missing"):
        presentation._contract()
    assert not marker.exists()


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        pytest.param(b'[project]\nname = "benchweave"\n', "benchweave", id="ordinary"),
        pytest.param(b"[project]\nname = \"caf\xe9\"\n", None, id="not-utf-8"),
        pytest.param(b'project = "not a table"\n', None, id="project-is-not-a-table"),
        pytest.param(b"[project]\nname = 5\n", None, id="name-is-not-a-string"),
        pytest.param(b"[project\n", None, id="not-toml"),
    ],
)
def test_project_name_is_none_when_unreadable(
    tmp_path: Path, content: bytes, expected: str | None
) -> None:
    (tmp_path / "pyproject.toml").write_bytes(content)
    assert validation._project_name(tmp_path) == expected


def test_project_name_is_none_without_a_pyproject(tmp_path: Path) -> None:
    assert validation._project_name(tmp_path) is None
