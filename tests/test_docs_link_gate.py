# author: Stephen Eaton
"""The docs citation gate derives its pattern from great-docs.yml and
refuses a vacuous match set (gateway #401, fold F1).

The disarmed-gate class this pins: an earlier revision hard-coded the old
GitHub Pages host inside a regex-escaped literal, invisible to host-form
census greps. When the link sweep moved every citation onto the project
domain, the literal matched nothing and the inbound-citation CI check
passed green while checking zero citations. Two properties close the
class: the pattern must derive from the configured ``site_url`` (it can
never disagree with the site the citations target), and an empty citation
match set must be a loud failure, never a green run that checked nothing.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "check_docs_links.py"

_spec = importlib.util.spec_from_file_location("check_docs_links", _SCRIPT)
assert _spec is not None and _spec.loader is not None
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _configured_base() -> str:
    text = (_REPO / "great-docs.yml").read_text(encoding="utf-8")
    base = re.search(r"^site_url:\s*(\S+)", text, re.MULTILINE)
    assert base is not None, "great-docs.yml must carry site_url"
    return base.group(1) if base.group(1).endswith("/") else base.group(1) + "/"


def test_the_pattern_derives_from_the_configured_site_url(tmp_path: Path) -> None:
    yml = tmp_path / "great-docs.yml"
    yml.write_text("site_url: https://example.dev/docs/\n", encoding="utf-8")
    pattern = gate.citation_pattern(yml)
    assert pattern.findall("see https://example.dev/docs/guide.html now") == ["guide.html"]
    # Other hosts — including the retired Pages host — never match.
    assert pattern.findall("https://madeinoz67.github.io/benchweave-sdk/docs/guide.html") == []
    assert pattern.findall("https://elsewhere.dev/docs/guide.html") == []


def test_a_missing_site_url_refuses_rather_than_guessing(tmp_path: Path) -> None:
    yml = tmp_path / "great-docs.yml"
    yml.write_text("title: only\n", encoding="utf-8")
    with pytest.raises(ValueError, match="site_url"):
        gate.citation_pattern(yml)


def test_the_real_citations_match_the_configured_host() -> None:
    """The live anti-vacuity contract: the configured host's own citations
    in the real README/CLAUDE.md are found — the state the old escaped
    literal silently lost (#401)."""
    pattern = gate.citation_pattern()
    citations: set[str] = set()
    for source in gate.CITED_IN:
        citations.update(pattern.findall((_REPO / source).read_text(encoding="utf-8")))
    assert citations, "the citation gate found no citations — vacuous state"


def _built_tree_with_sitemap(tmp_path: Path, loc_url: str) -> Path:
    docs = tmp_path / "site" / "docs"
    docs.mkdir(parents=True)
    (docs / "index.html").write_text("<html></html>", encoding="utf-8")
    (docs / "sitemap.xml").write_text(
        f"<urlset><url><loc>{loc_url}</loc></url></urlset>", encoding="utf-8"
    )
    return docs


def test_an_empty_citation_set_is_a_loud_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A README/CLAUDE.md pair citing no docs pages must fail the gate —
    never pass green over an empty match set (the disarmed-gate shape)."""
    docs = _built_tree_with_sitemap(tmp_path, "https://example.dev/docs/x.html")
    (tmp_path / "README.md").write_text("no citations here", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("none here either", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert gate.main(str(docs)) == 1
    assert "vacuous" in capsys.readouterr().out


def test_a_citation_against_the_configured_host_passes_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _configured_base()
    docs = _built_tree_with_sitemap(tmp_path, f"{base}guide.html")
    (tmp_path / "README.md").write_text(f"see {base}guide.html\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("see the README\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert gate.main(str(docs)) == 0
