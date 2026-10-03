"""Link-integrity check over the assembled docs tree (issue #347 WS4, fold B-F1).

The landing-page promotion defect this script exists to catch: great-docs'
``homepage: user_guide`` option renders the first user-guide page as the site
root, but the page's own relative links and every inbound URL that names the
page's normal location keep pointing where the page no longer is. The result
is a site whose front door 404s in both directions — measured on the first
WS4 build, where the promoted landing page carried twelve dead hrefs and the
README and CLAUDE.md pointed at a page that did not exist.

Two checks, both over the BUILT tree (never the sources — only the renderer
knows where pages land):

1. Every internal ``href`` on the front-door surfaces this repository authors
   (the root ``index.html`` and every ``user-guide/*.html`` page) resolves to
   a file in the tree. External schemes, fragments, and query strings are
   skipped.
2. The sitemap contains every rendered page URL that the README and CLAUDE.md
   cite (their ``https://.../docs/...`` links are inbound contracts; a cited
   page missing from every reachable sitemap is a dead inbound link). The
   witnesses are the release-root sitemap and the ``v/dev`` render's
   sitemap. When the checkout is a branch (``HEAD`` differs from
   ``origin/main``), the dev render is built from ``origin/main`` and lags
   the branch BY DESIGN (the assemble script's own rule); a citation miss
   in that state is printed as context, not a failure. The flip class this
   row exists for is caught pre-merge at the source level by the sdk lane's
   static pins (homepage reverted, nav lists the page, citations name the
   canonical URL), and on merge pushes the strict sitemap half takes over.

Deliberately out of scope, named rather than silently skipped: the renderer's
own generated surfaces (``reference/**``, ``contributing.html``,
``security.html``), the versioned buckets under ``v/`` (the approximated
historical renders), and hrefs into ``reference/`` at any depth — great-docs'
auto-linker emits dotted-symbol reference targets from prose mentions, and
the rendered reference layout does not carry those pages at those paths; the
pre-WS4 guide already shipped sixteen of them (measured in the v0.4.1
bucket), so the class predates this check. Hrefs may resolve to a directory
as well as a file: the assembly's own site-home links (``../``, ``../../``)
target the static website root above ``docs/`` and are valid in deployment.
This check owns the pages we author and the inbound citation contract;
widening it is a separate decision with those queues behind it.

Exits 0 when clean; prints each violation and exits 1 otherwise. Stdlib only
(the docs lane installs no Python dependencies beyond the build tools).
"""

from __future__ import annotations

import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

HREF = re.compile(r'https://madeinoz67\.github\.io/benchweave-sdk/docs/([^\s"\)<>]+)')
CITED_IN = ("README.md", "CLAUDE.md")


def _head_matches_origin_main() -> bool:
    """The strict-citation witness: HEAD is origin/main (a main push, or a
    local verification of main itself). On a branch the dev render is built
    from origin/main and lags the branch by the assemble script's own rule."""

    def rev(reference: str) -> str | None:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", reference],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.stdout.strip() if proc.returncode == 0 else None

    head = rev("HEAD")
    return head is not None and head == rev("origin/main")


def checked_pages(root: Path) -> list[Path]:
    pages = [root / "index.html"]
    pages += sorted((root / "user-guide").glob("*.html")) if (root / "user-guide").is_dir() else []
    return [page for page in pages if page.is_file()]


class _HrefCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name == "href" and value is not None:
                self.hrefs.append(value)


def main(root_text: str = "site/docs") -> int:
    root = Path(root_text)
    if not root.is_dir():
        print(f"docs_link_check: {root} is not a directory — build the site first")
        return 1
    violations: list[str] = []

    pages = checked_pages(root)
    for page in pages:
        collector = _HrefCollector()
        collector.feed(page.read_text(encoding="utf-8", errors="replace"))
        for href in collector.hrefs:
            if href.startswith(("http://", "https://", "mailto:", "data:", "#")):
                continue
            target = href.split("#", 1)[0].split("?", 1)[0]
            if not target or "/reference/" in f"/{target}" or target.startswith("reference/"):
                continue  # renderer auto-linker class — see the scope note above
            # Hrefs are relative to the page that carries them, not to the root;
            # a directory target is valid navigation (the assembly's own
            # site-home links point above docs/ at the static website root).
            resolved = (page.parent / target).resolve()
            if not (resolved.is_file() or resolved.is_dir()):
                violations.append(f"{page.relative_to(root)}: href {href!r} does not resolve")

    sitemap_texts = [
        path.read_text(encoding="utf-8")
        for path in (root / "sitemap.xml", root / "v" / "dev" / "sitemap.xml")
        if path.is_file()
    ]
    if not sitemap_texts:
        violations.append("no sitemap.xml in the built tree (root or v/dev)")
    strict = _head_matches_origin_main()
    for source in CITED_IN:
        text = Path(source).read_text(encoding="utf-8")
        for cited in sorted(set(HREF.findall(text))):
            if any(f"/{cited}" in sitemap for sitemap in sitemap_texts):
                continue
            if strict:
                violations.append(
                    f"{source}: cites docs page {cited!r} absent from every sitemap"
                )
            else:
                print(
                    f"  context (branch lag): {source} cites {cited!r}; the dev "
                    "render is origin/main and lags this branch by design"
                )

    if violations:
        print(f"docs_link_check: {len(violations)} violation(s)")
        for violation in violations:
            print(f"  {violation}")
        return 1
    print(f"docs_link_check: clean over {len(pages)} built pages")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
