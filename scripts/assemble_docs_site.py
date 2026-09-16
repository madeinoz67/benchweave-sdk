#!/usr/bin/env python3
"""Assemble the public BenchWeave SDK Pages site: static front door + versioned docs.

Implements the per-tag snapshot deploy design (docs-site plan Addendum B) with
the Task 12 two-tier layout — the hand-written static site from ``website/``
serves at the Pages root and the versioned docs tree serves under ``docs/``:

- ``website/`` (one page, four panels, per the public-site mockup; no build
  chain) is copied verbatim to the artifact root. Its links into the docs use
  relative ``docs/…`` paths, so the pair previews correctly from any server
  root, GitHub Pages included.
- Every release tag that carries a ``great-docs.yml`` at its ref is built in
  isolation (``great-docs build --from-repo … --branch <tag> --versions <tag>``)
  and overlaid into the docs tree under ``docs/v/<tag>/``; the latest stable
  tag additionally populates the ``docs/`` root; ``main`` builds to
  ``docs/v/dev/``.
- Pre-site tags (no ``great-docs.yml`` at their ref — v0.0.1/v0.0.2 today)
  cannot be isolated-built. One in-process multi-version build of the current
  tree produces their buckets instead: correct symbol sets via the tool's
  git_ref introspection at each tag, content/docstrings from the current tree
  (a disclosed approximation that isolated builds supersede from the next
  release onward). The approximated latest-stable render is copied from the
  ``docs/`` root into ``docs/v/<latest>/`` so every release has a stable
  bucket URL.
- The version list in ``great-docs.yml`` stays static and complete, so every
  bucket's version switcher lists all versions. Serving under the ``/docs/``
  subpath is safe by construction: page links are relative, the version
  switcher derives its base path from ``window.location.pathname`` at runtime,
  and ``site_url``/``seo.canonical.base_url`` carry the prefix for canonicals,
  sitemap and llms.txt.

Two assembly-level repairs on top of the tool's own output:

- ``v/latest/``/``v/stable/`` redirect stubs target ``/``, which is wrong for
  a project Pages site hosted under a path prefix; they are rewritten to the
  prefix derived from ``site_url`` (``/benchweave-sdk/docs/``).
- Isolated ``--from-repo`` builds install plain ``great-docs`` (no cairosvg),
  so raster favicons silently skip inside those buckets. The full favicon set
  is generated once at the docs root (cairosvg, when importable) and copied
  into any bucket that is missing it — cosmetic-only: pages reference the
  docs-root favicon absolutely and the SVG favicon is always present.

Any build failure aborts with a non-zero exit — this script runs in CI where
a docs failure must fail the job. Run from the repository root with
``great-docs`` on PATH (see .github/workflows/docs.yml).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
RASTER_FAVICONS = ("favicon.ico", "favicon-16x16.png", "favicon-32x32.png", "apple-touch-icon.png")
ALIASES = ("latest", "stable")


def log(msg: str) -> None:
    print(f"[assemble] {msg}")


def run(cmd: list[str], *, cwd: Path | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc.stdout


def release_tags() -> list[str]:
    """Release tags (vX.Y.Z) in ascending version order."""
    tags = run(["git", "tag", "--list", "v*"], cwd=REPO).split()
    parsed = [t for t in tags if TAG_RE.match(t)]
    return sorted(parsed, key=lambda t: tuple(int(g) for g in TAG_RE.match(t).groups()))  # type: ignore[union-attr]


def ref_has_config(ref: str) -> bool:
    """True if ``great-docs.yml`` exists at the given git ref."""
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{ref}:great-docs.yml"],
            cwd=REPO,
            capture_output=True,
        ).returncode
        == 0
    )


def yml_version_tags() -> set[str]:
    """Tags listed under ``versions:`` in great-docs.yml (for a staleness warning)."""
    text = (REPO / "great-docs.yml").read_text(encoding="utf-8")
    block = re.search(r"^versions:\n((?:[ \t]+.*\n?)+)", text, re.MULTILINE)
    if not block:
        return set()
    return set(re.findall(r"^\s*-?\s*tag:\s*(\S+)", block.group(1), re.MULTILINE))


def site_path_prefix() -> str:
    """URL path prefix of the deployed site (e.g. ``/benchweave-sdk/``)."""
    text = (REPO / "great-docs.yml").read_text(encoding="utf-8")
    m = re.search(r"^site_url:\s*(\S+)", text, re.MULTILINE)
    if not m:
        return "/"
    path = urlparse(m.group(1)).path or "/"
    return path if path.endswith("/") else path + "/"


def replace_dir(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def copy_website(dest: Path) -> None:
    """Copy the hand-written static site (``website/``) to the artifact root.

    The static site is the Pages front door; the docs tree lives under
    ``dest/docs/``. Loud failure if ``website/`` is missing or incomplete —
    a root without the static index would serve GitHub's 404 at the repo
    Pages URL.
    """
    src = REPO / "website"
    if not (src / "index.html").is_file():
        raise SystemExit(f"static website missing or incomplete: {src / 'index.html'} not found")
    shutil.copytree(src, dest, dirs_exist_ok=True)
    log(f"static site <- {src} (artifact root)")


def copy_root_tree(src: Path, dst: Path) -> None:
    """Copy a site root's content into dst, skipping an existing ``v/`` tree."""
    for entry in src.iterdir():
        if entry.name == "v":
            continue
        target = dst / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)


def bucket_source(out_dir: Path, tag: str) -> Path:
    """Source dir of one version inside an isolated build's output.

    A filtered ``--versions <tag>`` build renders the requested version either
    as a bucket (``out/v/<tag>/``, when the version is not the config's
    latest) or flat at the output root (when it is the latest). Both shapes
    are valid inputs here.
    """
    bucket = out_dir / "v" / tag
    if (bucket / "index.html").is_file():
        return bucket
    if (out_dir / "index.html").is_file():
        return out_dir
    raise SystemExit(
        f"isolated build output for {tag} has neither v/{tag}/ bucket nor flat index: {out_dir}"
    )


def isolated_build(great_docs: str, repo_url: str, ref: str, version: str, out_dir: Path) -> None:
    log(f"isolated build: --branch {ref} --versions {version} -> {out_dir}")
    run(
        [
            great_docs,
            "build",
            "--from-repo",
            repo_url,
            "--branch",
            ref,
            "--versions",
            version,
            "--output-dir",
            str(out_dir),
        ],
        cwd=REPO,
    )


def replace_root(src: Path, dest: Path) -> None:
    """Replace the site root (everything outside ``v/``) with an isolated build."""
    for entry in dest.iterdir():
        if entry.name == "v":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    shutil.copytree(src, dest, dirs_exist_ok=True)


def redirect_page(target: str) -> str:
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '  <meta charset="utf-8">\n'
        f'  <meta http-equiv="refresh" content="0; url={target}">\n'
        f'  <link rel="canonical" href="{target}">\n'
        "  <title>Redirecting…</title>\n"
        "</head>\n<body>\n"
        f'  <p>Redirecting to <a href="{target}">{target}</a>…</p>\n'
        "</body>\n</html>\n"
    )


def fix_alias_stubs(dest: Path, prefix: str) -> None:
    """Point ``v/latest/`` and ``v/stable/`` redirect stubs at the prefixed root.

    The tool writes ``url=/`` stubs, which redirect to the GitHub Pages ORIGIN
    root on a project site — one level too high.
    """
    for alias in ALIASES:
        stub = dest / "v" / alias / "index.html"
        if not stub.is_file():
            stub.parent.mkdir(parents=True, exist_ok=True)
            stub.write_text(redirect_page(prefix), encoding="utf-8")
            log(f"created missing alias stub v/{alias}/ -> {prefix}")
            continue
        html = stub.read_text(encoding="utf-8")
        if "url=/" in html:
            html = html.replace("url=/", f"url={prefix}").replace('href="/"', f'href="{prefix}"')
            stub.write_text(html, encoding="utf-8")
            log(f"rewrote alias stub v/{alias}/ redirect: / -> {prefix}")


def fit_to_square(img, size: int):  # noqa: ANN001 - PIL types stay local to the fallback path
    """Aspect-preserving fit onto a transparent square canvas (tool parity)."""
    from PIL import Image

    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
    return canvas


def generate_raster_favicons(dest: Path, logo: Path) -> None:
    """Generate the raster favicon set, mirroring great-docs' own pipeline."""
    import io

    import cairosvg
    from PIL import Image

    raw = Image.open(io.BytesIO(cairosvg.svg2png(url=str(logo), scale=4)))
    master = fit_to_square(raw, 512)
    for px, name in (
        (16, "favicon-16x16.png"),
        (32, "favicon-32x32.png"),
        (180, "apple-touch-icon.png"),
    ):
        master.resize((px, px), Image.Resampling.LANCZOS).save(dest / name, "PNG")
    master.save(dest / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])


def complete_favicons(dest: Path, logo: Path) -> None:
    """Ensure the favicon set exists at the root and in every version bucket.

    Isolated ``--from-repo`` builds cannot generate raster favicons (their
    temp venv installs plain ``great-docs``, without cairosvg), so the set is
    generated once at the root — when cairosvg is importable in this script's
    environment (the tool's supported extra: ``great-docs[svg]``) — and copied
    into buckets that lack it. Cosmetic-only, never a build failure.
    """
    if not all((dest / name).is_file() for name in RASTER_FAVICONS):
        try:
            generate_raster_favicons(dest, logo)
            log("generated raster favicon set at site root")
        except Exception as exc:  # noqa: BLE001 - loud cosmetic fallback
            log(
                f"WARNING: raster favicons missing at root and generation failed ({exc}); "
                "the SVG favicon remains — install 'great-docs[svg]' for the full set"
            )
    for name in (*RASTER_FAVICONS, "favicon.svg"):
        src = dest / name
        if not src.is_file():
            continue
        for bucket in (dest / "v").iterdir():
            if bucket.is_dir() and bucket.name not in ALIASES and not (bucket / name).is_file():
                shutil.copy2(src, bucket / name)


def verify_tree(dest: Path, tags: list[str], latest: str, dev_isolated: bool) -> None:
    docs = dest / "docs"
    failures = []
    if not (dest / "index.html").is_file():
        failures.append("static site root index.html missing (website/ not copied?)")
    if not (dest / "assets" / "logo.svg").is_file():
        failures.append("static site assets/logo.svg missing")
    if not (docs / "index.html").is_file():
        failures.append("docs root index.html missing (docs/ subpath build failed?)")
    for tag in tags:
        if not (docs / "v" / tag / "index.html").is_file():
            failures.append(
                f"docs/v/{tag}/index.html missing (is the tag in great-docs.yml 'versions:'?)"
            )
    if not (docs / "v" / "dev" / "index.html").is_file():
        failures.append("docs/v/dev/index.html missing")
    for alias in ALIASES:
        if not (docs / "v" / alias / "index.html").is_file():
            failures.append(f"alias docs/v/{alias}/ missing")
    if failures:
        raise SystemExit("assembled site verification FAILED:\n  " + "\n  ".join(failures))

    dev_source = (
        "isolated main build" if dev_isolated else "in-process current tree (pre-merge fallback)"
    )
    log(f"verification OK: static root + docs/=latest({latest}), dev source: {dev_source}")
    for path in sorted((docs / "v").iterdir()):
        if path.is_dir():
            log(f"  docs/v/{path.name}/  ({sum(1 for _ in path.rglob('*'))} files)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Assemble the versioned docs site (see module docstring)"
    )
    ap.add_argument("--repo-url", default="https://github.com/madeinoz67/benchweave-sdk.git")
    ap.add_argument("--dest", default="site")
    ap.add_argument("--main-branch", default="main")
    ap.add_argument("--staging", default=".docs-assembly")
    ap.add_argument("--great-docs", default=shutil.which("great-docs") or "great-docs")
    ap.add_argument(
        "--skip-isolated",
        action="store_true",
        help="build only the in-process tree (debug; no true per-tag snapshots)",
    )
    args = ap.parse_args()

    dest = (REPO / args.dest).resolve()
    staging = (REPO / args.staging).resolve()
    if dest.exists():
        shutil.rmtree(dest)  # hermetic: no stale content from a previous layout survives a re-run
    docs_root = dest / "docs"
    tags = release_tags()
    if not tags:
        raise SystemExit("no release tags (vX.Y.Z) found — nothing to assemble")
    latest = tags[-1]

    missing = [t for t in tags if t not in yml_version_tags()]
    if missing:
        log(f"WARNING: release tags absent from great-docs.yml versions: {missing}")

    # ── 1. In-process base build: current tree + approximated historical buckets ──
    inproc_versions = [t for t in tags if not ref_has_config(t)] + ["dev"]
    if inproc_versions:
        log(f"in-process multi-version build (--versions {','.join(inproc_versions)})")
        cache = REPO / ".great-docs-cache"
        if cache.exists():
            shutil.rmtree(cache)  # hermetic: tag snapshots must reflect current config
        proc = subprocess.run(
            [args.great_docs, "build", "--versions", ",".join(inproc_versions)], cwd=REPO
        )
        if proc.returncode != 0:
            raise SystemExit(f"in-process docs build failed ({proc.returncode})")
        replace_dir(REPO / "great-docs" / "_site", docs_root)
    else:
        docs_root.mkdir(parents=True, exist_ok=True)
        (docs_root / "v").mkdir(exist_ok=True)
        log("all release tags carry great-docs.yml — no in-process historical buckets needed")

    dev_isolated = False
    staging.mkdir(parents=True, exist_ok=True)

    # ── 2. Isolated per-tag builds: true snapshots for tags with a config at their ref ──
    if not args.skip_isolated:
        for tag in tags:
            if not ref_has_config(tag):
                log(f"v/{tag}/: no great-docs.yml at ref — keeping in-process approximated bucket")
                continue
            out_dir = staging / tag
            isolated_build(args.great_docs, args.repo_url, tag, tag, out_dir)
            src = bucket_source(out_dir, tag)
            replace_dir(src, docs_root / "v" / tag)
            if tag == latest:
                replace_root(src, docs_root)
                log(f"docs/ root <- isolated build of {tag} (latest stable)")
            log(f"docs/v/{tag}/ <- isolated build at ref {tag}")

        # ── 3. Dev bucket from main (isolated), with the pre-merge PR fallback ──
        main_ref = f"origin/{args.main_branch}"
        has_origin_main = (
            subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", main_ref],
                cwd=REPO,
                capture_output=True,
            ).returncode
            == 0
        )
        if has_origin_main and ref_has_config(main_ref):
            out_dir = staging / "dev"
            isolated_build(args.great_docs, args.repo_url, args.main_branch, "dev", out_dir)
            replace_dir(bucket_source(out_dir, "dev"), docs_root / "v" / "dev")
            dev_isolated = True
        else:
            log(
                f"{main_ref} has no great-docs.yml (pre-merge PR build) — "
                "keeping in-process v/dev/ from the current tree"
            )
    else:
        log("--skip-isolated: dev + historical buckets are all in-process renders")

    # ── 4. Approximated latest-stable bucket: copy of the root render ──
    if not ref_has_config(latest) and not (docs_root / "v" / latest / "index.html").is_file():
        root_copy = staging / "root-copy"
        if root_copy.exists():
            shutil.rmtree(root_copy)
        root_copy.mkdir(parents=True)
        copy_root_tree(docs_root, root_copy)
        replace_dir(root_copy, docs_root / "v" / latest)
        log(f"docs/v/{latest}/ <- copy of docs root (in-process latest render; approximated bucket)")

    # ── 5. Static front door at the root, then repairs: alias stubs, favicons ──
    copy_website(dest)
    fix_alias_stubs(docs_root, site_path_prefix())
    complete_favicons(docs_root, REPO / "docs" / "assets" / "logo.svg")

    verify_tree(dest, tags, latest, dev_isolated)
    log(f"assembled site at {dest}")


if __name__ == "__main__":
    main()
