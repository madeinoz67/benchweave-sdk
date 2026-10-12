"""Vendored UI assets, digest-verified at construction (NFR-P3).

The host owns its shell assets (``htmx.min.js``, ``bw-events.js``,
``standalone.css``): ``inventory.json`` lists every host-owned file with
its size and sha256, and :func:`verify_ui_assets` re-checks each one —
same traversal refusals, prefixed ``standalone_ui_asset_*`` — so tampered
or missing assets refuse startup instead of serving.

The renderer's design tokens (``tokens.css``, ``themes.css") come from
the installed ``benchweave-ui-html`` package (PRD 12 Q5: freshness
arrives by release and an exact pin bump in this repository, never by a
copied template — the pin closes design record I1's deferral D5). Those
bytes are verified by the PACKAGE's own verifier, which this module
calls (:func:`verify_renderer_assets`) — one verifier per byte set, no
second digest list for the same files here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

#: The vendored asset root inside this package, verified on every call.
INVENTORY_API_VERSION = 1

#: The renderer-owned assets served from the installed ui-html package
#: (never from this package's tree — Q5's release-plus-pin mechanism).
#: ``globals.css`` joins at I2a (D-B3, SW-22): the partials' component
#: classes are meaningless without the package's own global rules.
#: ``bw-host.js`` joins with issue #449 slice 1: the package's host script
#: drives the root ``data-theme`` from ``prefers-color-scheme`` (dark
#: parity with the gateway console, whose shell loads the same bytes) and
#: its CSRF-stamping listener is inert here — the host renders no
#: ``bw-csrf-token`` meta (its forms carry explicit ``hx-headers``).
RENDERER_ASSETS = frozenset({"tokens.css", "themes.css", "globals.css", "bw-host.js"})

#: The manifest-declared local override (issue #449 slice 1, design
#: §3.1.4): a plugin declaring an ``assets[]`` row whose ``path`` is
#: exactly this name gets those bytes served as an override stylesheet,
#: AFTER the package's token stylesheets, on the preview host's pages.
#: Digest-verified at serve time against the manifest's own pin; oversize
#: bytes refuse; ``preview.css`` is preview-host-only — the gateway never
#: reads a plugin's asset tree.
PREVIEW_OVERRIDE_ASSET = "preview.css"

#: The override stylesheet's size cap (design §3.1.4).
PREVIEW_OVERRIDE_MAX_BYTES = 64 * 1024

#: The machine-matchable refusal prefix for a declared override that
#: refuses to serve (digest mismatch, oversize, unreadable).
PREVIEW_OVERRIDE_REFUSED = "standalone_preview_override_refused:"


def renderer_assets_root() -> Path:
    """The installed ``benchweave_ui_html`` assets directory."""
    from benchweave_ui_html.assets import ASSETS_DIR

    return Path(ASSETS_DIR)


def verify_renderer_assets() -> None:
    """Verify the renderer's assets with the PACKAGE's own verifier.

    One verifier per byte set: the installed package carries its own
    inventory and digest discipline, and this call defers to it — the
    host never re-hashes bytes another package owns. Tampered or missing
    bytes refuse startup (``standalone_ui_asset_renderer:``).
    """
    from benchweave_ui_html.assets import verify_vendored_assets

    refusals = verify_vendored_assets()
    if refusals:
        raise ValueError(
            f"standalone_ui_asset_renderer: {'; '.join(refusals)}"
        )


class PreviewOverrideRefused(ValueError):
    """A DECLARED ``preview.css`` override that refuses to serve.

    The page path catches this and renders the default tokens; the asset
    route translates it into the prefixed refusal response."""


def preview_override_bytes(manifest: Mapping[str, Any], resource_root: Path) -> bytes | None:
    """The plugin's declared override stylesheet, digest-verified, or None.

    Returns ``None`` when the manifest declares no ``preview.css`` row (the
    default-tokens default). A declared row is served only when the bytes
    on disk still match the manifest's own ``sha256`` pin and fit the size
    cap — the manifest's digest discipline, re-verified at serve time (the
    one-time load check cannot see a post-load tamper). Refusals raise
    :class:`PreviewOverrideRefused` carrying the machine-matchable prefix.

    Not caught: a manifest row whose declared ``sha256`` is not a digest
    shape — that row cannot pass the load-time schema, so it never reaches
    this comparison.
    """
    for asset in manifest.get("assets", []):
        if not isinstance(asset, Mapping) or asset.get("path") != PREVIEW_OVERRIDE_ASSET:
            continue
        try:
            raw = (resource_root / PREVIEW_OVERRIDE_ASSET).read_bytes()
        except OSError as exc:
            raise PreviewOverrideRefused(
                f"{PREVIEW_OVERRIDE_REFUSED} preview.css is unreadable"
            ) from exc
        if len(raw) > PREVIEW_OVERRIDE_MAX_BYTES:
            raise PreviewOverrideRefused(
                f"{PREVIEW_OVERRIDE_REFUSED} preview.css exceeds the "
                f"{PREVIEW_OVERRIDE_MAX_BYTES // 1024} KiB cap"
            )
        declared = str(asset.get("sha256", ""))
        if hashlib.sha256(raw).hexdigest() != declared:
            raise PreviewOverrideRefused(
                f"{PREVIEW_OVERRIDE_REFUSED} preview.css bytes differ from "
                "the manifest pin"
            )
        return raw
    return None


def ui_assets_root() -> Path:
    """The vendored asset root inside this package, verified on every call."""
    root = Path(__file__).with_name("ui_assets")
    verify_ui_assets(root)
    return root


def verify_ui_assets(root: Path) -> None:
    """Refuse unless every inventory row matches the bytes on disk.

    Raises
    ------
    ValueError
        ``standalone_ui_asset_inventory_invalid`` for an unreadable or
        wrong-shape inventory, ``standalone_ui_asset_unsafe`` for a
        traversal-shaped path, ``standalone_ui_asset_tampered`` for a size
        or digest mismatch.
    """
    try:
        inventory = json.loads((root / "inventory.json").read_bytes())
        assets = inventory["assets"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("standalone_ui_asset_inventory_invalid") from exc
    if inventory.get("api_version") != INVENTORY_API_VERSION or not isinstance(
        assets, list
    ) or not assets:
        raise ValueError("standalone_ui_asset_inventory_invalid")
    for asset in assets:
        relative = PurePosixPath(str(asset.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
            raise ValueError(f"standalone_ui_asset_unsafe: {relative}")
        try:
            content = (root / relative).read_bytes()
        except OSError as exc:
            raise ValueError(f"standalone_ui_asset_tampered: {relative}") from exc
        if (
            len(content) != asset.get("size")
            or hashlib.sha256(content).hexdigest() != asset.get("sha256")
        ):
            raise ValueError(f"standalone_ui_asset_tampered: {relative}")


def build_inventory(root: Path) -> dict[str, object]:
    """Regenerate the inventory document from the bytes on disk.

    The committed ``inventory.json`` is data this function emits; the assets
    test regenerates and compares, so a vendored byte can never move without
    its inventory row moving with it.
    """
    assets = []
    for path in sorted(root.iterdir()):
        if path.name == "inventory.json" or not path.is_file():
            continue
        raw = path.read_bytes()
        assets.append(
            {
                "path": path.name,
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return {"api_version": INVENTORY_API_VERSION, "assets": assets}
