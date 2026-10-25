"""Offline UI authoring helpers; successful validation is never device approval.

The ``migrate_ui`` lane (issue #460) refuses with these ``snake_case:`` prefixes
(STD-4): ``migrate_ui_ahead:`` (a document above the lock's active — install the
newer SDK, never a downgrade write), ``migrate_ui_version_absent:`` (a document
that is unparseable or carries no version-shaped ``contract_version``),
``migrate_ui_stamp_unlocatable:`` (the version value parses but its byte pattern
cannot be located for in-place re-stamping), and
``migrate_ui_invalid_after_stamp:`` (the re-stamped set fails the same vendored
validation ``check-ui`` runs; nothing is written). The class-reference ledger's
motion (#541 slice 2) adds ``migrate_ui_composed_unresolved:`` (a ledger-named
composed class whose pin cannot re-resolve or no longer validates under the
target family) and ``migrate_ui_ledger_drift:`` (the ledger's custom/composed
inventories disagree with arithmetic over the current descriptor and pins —
keyed to the classes and members the derivation APPLIES, so a pin-declared
class whose claims name no declared action is disclosed, never drift
[R1, 2026-10-23 fold wave 3]; a derive-ui motion, never a version write).
"""

from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from .served import _tuple, _tuple_or_none, active_version
from .validation import contract_documents, validate_descriptor


@dataclass(frozen=True, slots=True)
class ValidatedPreviewInputs:
    """Parsed inputs proven to match the existing presentation validator."""

    envelope: dict[str, Any]
    manifest: dict[str, Any]
    binding_catalogue: dict[str, Any]
    resource_root: Path


@cache
def _contract() -> Any:
    name = "benchweave_sdk._presentation_contract"
    vendored = Path(__file__).with_name("standards") / "plugin-ui" / "contracts.py"
    if not vendored.is_file():
        # The vendored tree is committed (and, in distributions, verified
        # against its lock by the build hook), so a missing validator is an
        # incomplete tree — never a cue to execute code from outside the
        # package.
        raise RuntimeError(
            "SDK presentation validator missing; run sync-standards or reinstall the SDK"
        )
    spec = importlib.util.spec_from_file_location(name, vendored)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the SDK presentation validator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@cache
def schemas() -> dict[str, Any]:
    # Cached: the expansion walks every contract document and is re-requested
    # for each envelope/preset validation; the corpus never changes in-process.
    result = dict(contract_documents())
    for document in tuple(result.values()):
        if "$id" in document:
            result[document["$id"]] = document
        for action in document.get("actions", {}).values():
            for key in ("input_schema", "output_schema"):
                schema = action.get(key, {})
                if "$id" in schema:
                    result[schema["$id"]] = schema
    return result


def _pinned_schemas(descriptor: dict[str, Any]) -> dict[str, Any]:
    """The served document map for the validator's profile-row scan: the OTDP
    catalogs — the profile/action row carriers — follow the descriptor's own
    pin, while $id-addressed documents stay served-wide (urn:otdp:measurement:
    0.2.0 resolves only from 0.2.0's measurement schema; the $id was retired
    from the 0.2.1+ schemas). Without the catalog scope, two served versions
    whose profile rows legitimately evolved read as a profile_shadow refusal
    in the vendored twin's flat scan over every document's rows."""
    scoped = dict(schemas())
    pin = descriptor.get("otdp_version")
    if not isinstance(pin, str) or not pin:
        pin = active_version("otdp")
    prefix = f"otdp/{pin}/"
    stale = [
        key
        for key in scoped
        if isinstance(key, str)
        and key.startswith("otdp/")
        and key.endswith("device-profile-catalog.json")
        and not key.startswith(prefix)
    ]
    for key in stale:
        del scoped[key]
    return scoped


def pinned_contract_documents(
    descriptor: dict[str, Any], descriptor_path: Path
) -> dict[str, dict[str, Any]]:
    """The descriptor's digest-pinned plugin contract documents, read and
    verified (#556 track B B4: the seam the composed-member mechanism rides).
    Every non-``urn:otdp:`` contracts row names a plugin-authored document
    beside the descriptor; the same integrity discipline as the classref
    walk's ``_vendor_documents`` applies here — unreadable, digest-mismatched
    and non-object pins refuse with the walk's own codes, and a pin that is
    not valid JSON refuses typed rather than surfacing the bare decoder
    error (the walk lets that one escape; this reader does not). The
    documents feed ``merge_pinned_documents`` so the validator's profile map
    and $id aliases see the pinned rows exactly as the served corpus's."""
    import hashlib

    documents: dict[str, dict[str, Any]] = {}
    for row in descriptor.get("contracts", []):
        identifier = str(row.get("id", ""))
        if identifier.startswith("urn:otdp:") or not identifier:
            continue
        path = descriptor_path.parent / str(row.get("path", ""))
        try:
            raw = read_file(path)
        except (ValueError, OSError) as exc:
            raise ValueError(
                "classref_vendor_catalog_unreadable: "
                f"pinned vendor catalog {row.get('path')} unreadable ({exc})"
            ) from exc
        if hashlib.sha256(raw).hexdigest() != row.get("sha256"):
            raise ValueError(
                "classref_vendor_catalog_digest_mismatch: "
                f"pinned vendor catalog {row.get('path')} digest mismatch"
            )
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "classref_vendor_catalog_invalid: "
                f"pinned vendor catalog {row.get('path')} is not valid JSON"
            ) from exc
        if not isinstance(document, dict):
            raise ValueError(
                "classref_vendor_catalog_invalid: "
                f"pinned vendor catalog {row.get('path')} is not a JSON object"
            )
        documents[str(row.get("path", ""))] = document
    return documents


def _open_no_follow(part: str, flags: int, directory: int) -> int:
    """Open one strict component, naming symlink refusals over raw errno prose.

    The O_NOFOLLOW walk refuses a symlinked component as ELOOP on Linux or
    ENOTDIR on macOS (where /tmp is a symlink); lstat confirms the component
    really is a symlink before the typed refusal is raised. Every other
    outcome — a regular file mid-path, a failed confirmation, any other
    errno — re-raises the original error unchanged.
    """
    try:
        return os.open(part, flags, dir_fd=directory)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            try:
                metadata = os.stat(part, dir_fd=directory, follow_symlinks=False)
            except OSError:
                raise exc from None  # confirmation failed: never mask the original
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(
                    f"path_symlink_component: {part}: canonical paths only, no symlink "
                    "components (on macOS use /private/tmp rather than /tmp)"
                ) from exc
        raise


#: The bounded-read cap every SDK file read shares (256 KiB). The provider-pin
#: path names this bound in its own refusal — a pinned document above it is
#: an SDK resource bound, not a semantic disagreement with the contract.
INPUT_BYTE_LIMIT = 262144


def read_file(path: Path, limit: int = INPUT_BYTE_LIMIT) -> bytes:
    """Open bounded regular files without following symlinks in any component.

    The same three outcomes on every platform: a symlinked component is
    refused as ``path_symlink_component:``; a special file or oversize input
    raises ``ValueError``; everything else keeps its ``OSError`` face — a
    directory target is ``IsADirectoryError``, a regular file sitting where
    a directory should be is ``NotADirectoryError``, and absence or
    permissions report whatever the platform does.
    """
    if limit < 0:
        raise ValueError("Input byte limit exceeded")
    if sys.platform == "win32":
        return _read_file_no_dirfd(path, limit)
    parts = path.absolute().parts
    directory = os.open(parts[0], os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[1:-1]:
            child = _open_no_follow(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, directory)
            os.close(directory)
            directory = child
        descriptor = _open_no_follow(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, directory
        )
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
                raise ValueError("Input must be a bounded regular file")
            raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise ValueError("Input byte limit exceeded")
            return raw
    finally:
        os.close(directory)


# IsReparseTagNameSurrogate: set on tags that stand in for another name
# (symlinks, junctions, mount points, WSL symlinks), clear on tags that only
# decorate an ordinary file (cloud-file placeholders, app execution aliases).
_REPARSE_NAME_SURROGATE = 0x20000000


def _redirects_name(details: os.stat_result) -> bool:
    """Whether an ``lstat`` result describes a component that redirects the path.

    A symlink does, and so does a Windows reparse point whose tag is a name
    surrogate. A reparse point that is not a name surrogate is an ordinary
    file that happens to carry a tag — ``os.lstat`` itself reports it as a
    regular file — so refusing it would refuse, for example, every document
    in a OneDrive-backed checkout.
    """
    if stat.S_ISLNK(details.st_mode):
        return True
    reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if not getattr(details, "st_file_attributes", 0) & reparse_point:
        return False
    return bool(getattr(details, "st_reparse_tag", 0) & _REPARSE_NAME_SURROGATE)


def _read_file_no_dirfd(path: Path, limit: int) -> bytes:
    """``read_file`` for platforms without ``O_NOFOLLOW``/``dir_fd`` (Windows).

    Each component is inspected with ``lstat`` and refused with the same
    ``path_symlink_component:`` prefix the POSIX walk uses when it redirects
    the name (``_redirects_name``); a regular file mid-path is named as the
    ``NotADirectoryError`` the POSIX walk reports, and any ``lstat`` failure
    re-raises unchanged. A same-file check after the open ties
    the descriptor back to the inspected final component. The residual race
    on intermediate components is accepted for an offline authoring tool; the
    POSIX branch keeps the race-free ``dir_fd`` walk.
    """
    # POSIX getcwd() is canonical by definition, so a relative input there is
    # never refused for how the working directory was reached, whereas
    # os.getcwd() on Windows keeps a junction it was entered through.
    # Canonicalise that prefix only: a path the caller spelled out in full
    # keeps the strict refusal, exactly as it does on POSIX.
    if path.is_absolute():
        resolved = path
    else:
        resolved = (Path(os.path.realpath(os.getcwd())) / path).absolute()
    current = Path(resolved.parts[0])
    details = os.lstat(current)
    for part in resolved.parts[1:]:
        if not stat.S_ISDIR(details.st_mode):
            # A regular file sitting where a directory should be. The POSIX
            # walk reports ENOTDIR; Windows' lstat of the child would only say
            # the path was not found, so name it here.
            raise NotADirectoryError(errno.ENOTDIR, os.strerror(errno.ENOTDIR), str(current))
        current = current / part
        details = os.lstat(current)
        if _redirects_name(details):
            raise ValueError(
                f"path_symlink_component: {part}: canonical paths only, no symlink, "
                "junction or mount-point components"
            )
    if stat.S_ISDIR(details.st_mode):
        # The POSIX walk reports a directory target as IsADirectoryError; opening
        # one on Windows fails as a misleading PermissionError, so say it here.
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(resolved))
    if not stat.S_ISREG(details.st_mode):
        raise ValueError("Input must be a bounded regular file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    descriptor = os.open(resolved, flags)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError("Input must be a bounded regular file")
        # samestat against the WALK's own lstat of the final component, not a
        # fresh post-open lstat: the descriptor is thereby tied to the very
        # file that was verified not to be a symlink or reparse point, which
        # closes the swap-in/swap-out window a re-run lstat would miss.
        if not os.path.samestat(metadata, details):
            raise ValueError("Input path changed while being read")
        raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Input byte limit exceeded")
        return raw


def validate_preset(
    raw: bytes,
    *,
    descriptor_raw: bytes,
    settings_schema_raw: bytes,
    firmware: str | None,
    action_id: str | None = None,
) -> Any:
    """Validate one complete configuration preset, offline, from bytes already in hand.

    The descriptor is validated first; the preset is then checked against the
    plugin's settings schema by the vendored plugin-ui validator, the same
    bytes the gateway runs. A clean report is not approval to apply settings.

    Parameters
    ----------
    raw
        The preset document.
    descriptor_raw
        The plugin's device descriptor.
    settings_schema_raw
        The JSON Schema the preset's settings must satisfy.
    firmware
        Firmware version the preset is judged against, or None.
    action_id
        The configuration action the preset targets, when the descriptor
        offers more than one.

    Returns
    -------
    object
        The vendored validator's report: ``valid``, ``findings`` (each with
        ``code``, ``path`` and ``message``) and ``unavailable_pages``.
    """
    contract = _contract()
    try:
        descriptor = contract.parse_document(descriptor_raw)
    except contract.DocumentError as exc:
        # The preset side types a reader-refused document as a finding; the
        # descriptor side matches it instead of leaking the bare
        # DocumentError (RedTeam PT-7 E4).
        return contract.ValidationReport(
            (contract.Finding(exc.code, "descriptor", str(exc)),)
        )
    validate_descriptor(descriptor)
    return contract.validate_preset(
        raw,
        descriptor_raw=descriptor_raw,
        settings_schema_raw=settings_schema_raw,
        schema_documents=_pinned_schemas(descriptor),
        firmware=firmware,
        action_id=action_id,
    )


def resolve_preset_action(raw: bytes, *, descriptor_raw: bytes) -> str | None:
    """Resolve the corpus action a preset's settings schema identifies.

    The same resolver ``validate_preset`` uses, exported so the CLI's
    envelope note cannot disagree with the enforcement: ``None`` means the
    settings schema carries a custom ``$id`` and lane 1 applies no envelope.
    """
    try:
        descriptor = _contract().parse_document(descriptor_raw)
    except _contract().DocumentError as exc:
        # The resolver returns str | None, so a reader-refused descriptor
        # surfaces as a typed, code-carrying ValueError — never the bare
        # DocumentError (RedTeam PT-7 E4).
        raise ValueError(f"descriptor_document_{exc.code}: {exc}") from exc
    validate_descriptor(descriptor)
    resolved: str | None = _contract().resolve_preset_action(
        _contract().parse_document(raw), schemas()
    )
    return resolved


def validate_presentation(
    envelope_raw: bytes,
    *,
    descriptor_raw: bytes,
    resources: dict[str, bytes],
    binding_catalogue: dict[str, Any],
    supported_features: frozenset[str] = frozenset(),
    supported_panels: frozenset[str] = frozenset(),
    firmware: str | None = None,
    pinned_documents: dict[str, dict[str, Any]] | None = None,
) -> Any:
    """Validate a presentation candidate, offline, from bytes already in hand.

    No file is read here: the caller supplies the envelope, the descriptor
    and every resource the envelope's manifest lists (``check_ui`` is the
    variant that loads them from disk). A clean report is not admission.

    Parameters
    ----------
    envelope_raw
        The presentation envelope.
    descriptor_raw
        The plugin's device descriptor.
    resources
        Resource bytes keyed by their path under the envelope's resource root.
    binding_catalogue
        The parsed binding catalogue the manifest's bindings resolve against.
    supported_features, supported_panels
        What the renderer under test supports; pages needing more are reported
        as unavailable rather than invalid.
    firmware
        Firmware version the candidate is judged against, or None.
    pinned_documents
        The descriptor's digest-verified plugin contract documents, keyed by
        pin path (``pinned_contract_documents``); when supplied they merge
        into the served document set through the vendored
        ``merge_pinned_documents`` guard, so a composed-member declaration's
        vendor profile row and a vendor catalog's action schemas resolve for
        the targets that name them (#556 track B B4 — without the merge a
        vendor target reports ``capability_mismatch`` at the real
        ``check-ui``). A pin that shadows a served ``$id`` reports as a
        ``pinned_id_shadow`` finding, the same posture as every other
        reader-refused document.

    Returns
    -------
    object
        The vendored validator's report: ``valid``, ``findings`` (each with
        ``code``, ``path`` and ``message``) and ``unavailable_pages``.
    """
    contract = _contract()
    try:
        descriptor = contract.parse_document(descriptor_raw)
    except contract.DocumentError as exc:
        return contract.ValidationReport(
            (contract.Finding(exc.code, "descriptor", str(exc)),)
        )
    validate_descriptor(descriptor)
    documents: dict[str, Any] = _pinned_schemas(descriptor)
    if pinned_documents:
        try:
            documents = contract.merge_pinned_documents(
                documents, pinned_documents
            )
        except contract.DocumentError as exc:
            return contract.ValidationReport(
                (contract.Finding(exc.code, "descriptor.contracts", str(exc)),)
            )
    return contract.validate_presentation(
        envelope_raw,
        descriptor_raw=descriptor_raw,
        resources=resources,
        binding_catalogue=binding_catalogue,
        schema_documents=documents,
        supported_features=supported_features,
        supported_panels=supported_panels,
        firmware=firmware,
    )


def _load_ui_candidate(
    envelope_path: Path,
    descriptor_path: Path,
    root: Path,
    catalogue_path: Path,
    *,
    firmware: str | None,
    features: frozenset[str],
    panels: frozenset[str],
) -> tuple[Any, ValidatedPreviewInputs]:
    contract = _contract()
    envelope_raw = read_file(envelope_path)
    envelope = contract.parse_document(envelope_raw)
    try:
        resource_root = envelope["resource_root"]
        manifest_path = envelope["manifest"]["path"]
        if not contract.safe_resource_path(resource_root) or not contract.safe_resource_path(
            manifest_path
        ):
            raise ValueError("Unsafe presentation resource path")
        base = root / resource_root
        manifest_raw = read_file(base / manifest_path)
        manifest = contract.parse_document(manifest_raw)
        assets = manifest.get("assets", [])
        if not isinstance(assets, list) or len(assets) > 256:
            raise ValueError("Asset collection exceeds limit")
        resources = {manifest_path: manifest_raw}
        total = len(manifest_raw)
        for asset in assets:
            name = asset["path"]
            if not contract.safe_resource_path(name):
                raise ValueError("Unsafe asset path")
            if name not in resources:
                raw = read_file(base / name, min(16 * 1024 * 1024, 64 * 1024 * 1024 - total))
                resources[name] = raw
                total += len(raw)
        catalogue = contract.parse_document(read_file(catalogue_path))
        descriptor_bytes = read_file(descriptor_path)
        # (#556 track B B4) The pinned-document merge rides the production
        # path: the descriptor's digest-verified plugin documents join the
        # served set here, so a composed-member declaration's vendor profile
        # row — and a vendor catalog's action schemas — resolve for the
        # targets that name them. Integrity refusals carry the walk's own
        # codes: a broken pin refuses the check exactly as it refuses the
        # derive.
        descriptor_document = contract.parse_document(descriptor_bytes)
        report = validate_presentation(
            envelope_raw,
            descriptor_raw=descriptor_bytes,
            resources=resources,
            binding_catalogue=catalogue,
            supported_features=features,
            supported_panels=panels,
            firmware=firmware,
            pinned_documents=pinned_contract_documents(
                descriptor_document, descriptor_path
            ),
        )
        return report, ValidatedPreviewInputs(envelope, manifest, catalogue, base)
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed presentation resource references") from exc


def check_ui(
    envelope_path: Path,
    descriptor_path: Path,
    root: Path,
    catalogue_path: Path,
    *,
    firmware: str | None,
    features: frozenset[str],
    panels: frozenset[str],
) -> Any:
    """Load a presentation candidate from disk and validate it; what ``check-ui`` runs.

    Every file is read through ``read_file``, so a symlinked component is
    refused, and nothing outside ``root`` is read: a resource root or
    manifest path that leaves it is refused before any read.

    Parameters
    ----------
    envelope_path, descriptor_path, catalogue_path
        The presentation envelope, the device descriptor and the binding catalogue.
    root
        The package resource root the envelope's paths are relative to.
    firmware
        Firmware version the candidate is judged against, or None.
    features, panels
        What the renderer under test supports.

    Returns
    -------
    object
        The vendored validator's report: ``valid``, ``findings`` (each with
        ``code``, ``path`` and ``message``) and ``unavailable_pages``.

    Raises
    ------
    ValueError
        For an unsafe resource path, a symlinked component
        (``path_symlink_component:``) or an oversize input.
    OSError
        For a file that is absent or unreadable.
    """
    report, _ = _load_ui_candidate(
        envelope_path,
        descriptor_path,
        root,
        catalogue_path,
        firmware=firmware,
        features=features,
        panels=panels,
    )
    return report


def load_validated_preview_inputs(
    envelope_path: Path,
    descriptor_path: Path,
    root: Path,
    catalogue_path: Path,
    *,
    firmware: str | None,
    features: frozenset[str],
    panels: frozenset[str],
) -> ValidatedPreviewInputs:
    """Load a presentation candidate as ``check_ui`` does, and insist that it is valid.

    The preview server is built from the parsed inputs this returns, so a
    candidate the checker rejects can never be previewed (SRF-2).

    Parameters
    ----------
    envelope_path, descriptor_path, catalogue_path
        The presentation envelope, the device descriptor and the binding catalogue.
    root
        The package resource root the envelope's paths are relative to.
    firmware
        Firmware version the candidate is judged against, or None.
    features, panels
        What the renderer under test supports.

    Returns
    -------
    ValidatedPreviewInputs
        The parsed envelope, manifest and binding catalogue, with the resource root.

    Raises
    ------
    ValueError
        ``preview_invalid_presentation:`` with the first finding when the report
        is not valid; otherwise as ``check_ui``.
    """
    report, candidate = _load_ui_candidate(
        envelope_path,
        descriptor_path,
        root,
        catalogue_path,
        firmware=firmware,
        features=features,
        panels=panels,
    )
    if not report.valid:
        finding = report.findings[0]
        raise ValueError(
            f"preview_invalid_presentation: {finding.code}: {finding.path}: {finding.message}"
        )
    return candidate


@dataclass(frozen=True, slots=True)
class MigrationOutcome:
    """What one ``migrate_ui`` run did, as report lines for the CLI to render.

    ``noop`` marks the already-at-active case (no lines, nothing written —
    the plugin-ui documents AND the class-reference ledger all current).
    ``notes`` is reserved for advisory pointers that are not migration
    results; the classref-family staleness detection it used to carry was
    retired by the ledger's own re-stamp motion (#541 slice 2).
    """

    target: str
    lines: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    noop: bool = False


def _restamp(raw: bytes, *, key: str, old: str, new: str) -> tuple[bytes, int]:
    """Swap one raw-bytes JSON string value by exact key pattern.

    A targeted substitution, never a re-dump: key order, spacing and the
    trailing newline survive untouched, so the migration's diff is the value
    and nothing else. The count lets the caller refuse (never re-serialize)
    when the parsed value exists but the byte pattern does not.
    """
    pattern = re.compile(('("' + key + '"\\s*:\\s*")' + re.escape(old) + '(")').encode())
    return pattern.subn(b"\\g<1>" + new.encode() + b"\\g<2>", raw)


def _ledger_class_unresolved(class_urn: str, reasons: list[str]) -> ValueError:
    detail = "; ".join(reasons[:3]) if reasons else (
        "no pinned document declares this class urn under the current "
        "descriptor"
    )
    return ValueError(
        f"migrate_ui_composed_unresolved: class {class_urn}: {detail}"
    )


def _resolve_ledger_class(
    descriptor: dict[str, Any],
    descriptor_path: Path | None,
    class_urn: str,
) -> None:
    """Re-resolve one ledger-named composed class from its pin: path and
    sha256 from ``descriptor.contracts[]``, the bytes validated under the
    ACTIVE family's vendored composed schema (#541 slice 2, standards
    record §8.3-8.4 — the validation stamp only rides bytes the target
    schema admits).

    Every failure the walk sees is recorded and surfaces under
    ``migrate_ui_composed_unresolved`` when the class urn cannot be
    produced — the ledger named this class, so from migrate-ui's
    perspective a missing pin, a moved digest, an urn mismatch and a
    schema-invalid document are all "cannot re-resolve". The resolution
    walk's own integrity codes still govern the derive path; this walk
    attributes, it does not re-classify."""
    import hashlib

    # Body import: classref imports this module (read_file) at module
    # level, so the reverse import must be call-time — the same posture
    # the classref imports inside migrate_ui's callers use.
    from .classref import validate_composed_class

    reasons: list[str] = []
    for row in descriptor.get("contracts", []):
        if str(row.get("id", "")).startswith("urn:otdp:"):
            continue
        if descriptor_path is None:
            break
        path = descriptor_path.parent / str(row.get("path", ""))
        try:
            raw = read_file(path)
        except (ValueError, OSError) as exc:
            reasons.append(
                f"pinned document {row.get('path')} unreadable ({exc})"
            )
            continue
        if hashlib.sha256(raw).hexdigest() != row.get("sha256"):
            reasons.append(
                f"pinned document {row.get('path')} digest moved under its pin"
            )
            continue
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            reasons.append(f"pinned document {row.get('path')} not JSON ({exc})")
            continue
        if not isinstance(document, dict):
            continue
        if "actions" in document or not ("urn" in document and "claims" in document):
            # B1's fold mirror: the discrimination is conjunctive — a
            # document carrying only one of urn/claims is not this
            # class's document (and never a composed class at all).
            continue  # a vendor catalog pin, not this class's document
        if document.get("urn") != class_urn:
            continue  # a different composed class
        try:
            validate_composed_class(document, row.get("path"))
        except ValueError as exc:
            raise _ledger_class_unresolved(class_urn, [str(exc)]) from exc
        return
    raise _ledger_class_unresolved(class_urn, reasons)


def _migrate_classref_ledger(
    ledger_path: Path,
    descriptor_raw: bytes,
    descriptor_path: Path,
) -> tuple[bytes | None, list[str]]:
    """The class-reference ledger's family-bump motion (#541 slice 2,
    standards record §8): re-stamp ``contract_version``,
    ``reference_version`` and each ``composed_classes[].validated_against``
    to the classref family's active version, byte-in-place — only after
    every ledger-named class re-resolves and validates under the target,
    and only when the ledger's inventories match set arithmetic over the
    current descriptor and pins. A class urn's own version is content and
    is never re-stamped. Returns the new bytes (or None when nothing
    moves) plus one report line per moved surface; refuses
    ``migrate_ui_ledger_drift`` / ``migrate_ui_composed_unresolved`` /
    ``migrate_ui_version_absent`` / ``migrate_ui_ahead`` /
    ``migrate_ui_stamp_unlocatable`` with NOTHING written (the caller
    computes this before any write).
    """
    from .classref import composed_ledger_inventory

    raw = read_file(ledger_path)
    try:
        ledger = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"migrate_ui_version_absent: ui/class-reference.json: not JSON: {exc}"
        ) from exc
    if not isinstance(ledger, dict):
        raise ValueError(
            "migrate_ui_version_absent: ui/class-reference.json: not an object"
        )
    target = active_version("plugin-ui-class-reference")

    def _family_stamp(key: str) -> str:
        value = ledger.get(key)
        if not isinstance(value, str) or _tuple_or_none(value) is None:
            raise ValueError(
                f"migrate_ui_version_absent: ui/class-reference.json: no "
                f"version-shaped {key} ({value!r})"
            )
        if _tuple(value) > _tuple(target):
            raise ValueError(
                f"migrate_ui_ahead: ui/class-reference.json is at "
                f"plugin-ui-class-reference {value}, above this SDK's active "
                f"{target}; install the newer SDK that serves {value} — "
                "migrate-ui never writes versions down"
            )
        return value

    cv = _family_stamp("contract_version")
    rv = _family_stamp("reference_version")
    class_rows = ledger.get("composed_classes")
    if class_rows is None:
        class_rows = []
    if not isinstance(class_rows, list):
        raise ValueError(
            "migrate_ui_composed_unresolved: composed_classes must be a list"
        )
    try:
        descriptor = json.loads(descriptor_raw)
    except json.JSONDecodeError as exc:
        # N3 (2026-10-23 fold): a descriptor that does not parse is a
        # typed refusal, never a bare exception from the ledger walk.
        raise ValueError(
            f"migrate_ui_version_absent: descriptor.json is not JSON ({exc})"
        ) from exc
    if not isinstance(descriptor, dict):
        # N3: same class as B7 — a non-object descriptor with a ledger
        # present refused nothing before, it crashed ``.get`` on a list.
        raise ValueError(
            "migrate_ui_version_absent: descriptor.json is not a JSON object"
        )
    # The class re-resolution runs FIRST: a ledger-named class that cannot
    # re-resolve refuses under its own code before the inventory walk can
    # raise the resolution's integrity codes for the same broken pin.
    for row in class_rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("class"), str)
            or not isinstance(row.get("validated_against"), str)
        ):
            raise ValueError(
                f"migrate_ui_composed_unresolved: malformed composed_classes "
                f"row {row!r}"
            )
        # B4 (2026-10-23 fold): the validation stamp gets the same guards
        # its sibling family stamps get — a non-version-shaped value
        # refuses ``migrate_ui_version_absent`` (the re-stamp never
        # OVERWRITES a malformed stamp) and a value above the target
        # refuses ``migrate_ui_ahead`` (the re-stamp never writes the
        # validation record DOWN; the pre-fold walk silently wrote
        # ``"not-a-version"`` and ``"9.0.0"`` down to the target).
        stamp = row["validated_against"]
        if _tuple_or_none(stamp) is None:
            raise ValueError(
                "migrate_ui_version_absent: ui/class-reference.json: no "
                f"version-shaped validated_against ({stamp!r})"
            )
        if _tuple(stamp) > _tuple(target):
            raise ValueError(
                "migrate_ui_ahead: ui/class-reference.json carries a "
                f"composed class validated against {stamp}, above this "
                f"SDK's active {target}; install the newer SDK that serves "
                f"{stamp} — migrate-ui never writes versions down"
            )
        _resolve_ledger_class(descriptor, descriptor_path, row["class"])
    custom_set, composed_of, applied_classes = composed_ledger_inventory(
        descriptor, descriptor_path
    )
    drift: list[str] = []
    ledger_custom: set[str] = set()
    ledger_composed: set[str] = set()
    for key, collected in (
        ("custom_actions", ledger_custom),
        ("composed_actions", ledger_composed),
    ):
        rows = ledger.get(key)
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise ValueError(f"migrate_ui_ledger_drift: {key} must be a list")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("action"), str):
                drift.append(f"malformed {key} row {row!r}")
                continue
            collected.add(row["action"])
    for label, ledger_set, derived_set in (
        ("custom", ledger_custom, custom_set),
        ("composed", ledger_composed, set(composed_of)),
    ):
        for urn in sorted(ledger_set - derived_set):
            drift.append(
                f"the ledger's {label} inventory names {urn}, which the "
                "current descriptor and pins do not derive"
            )
        for urn in sorted(derived_set - ledger_set):
            drift.append(
                f"{urn} derives {label} but the ledger omits it"
            )
    # R6 (2026-10-23 fold, wave 3): the arithmetic carries the action ->
    # class MAPPING, not just the two sets — a ledger whose
    # ``composed_actions`` row named the WRONG class for a member
    # (inconsistent with its own ``composed_classes``) re-stamped green
    # with "nothing to do".
    ledger_composed_of: dict[str, str] = {}
    for row in ledger.get("composed_actions") or []:
        if (
            isinstance(row, dict)
            and isinstance(row.get("action"), str)
            and isinstance(row.get("class"), str)
        ):
            ledger_composed_of[row["action"]] = row["class"]
    for action, wrong in sorted(ledger_composed_of.items()):
        derives = composed_of.get(action)
        if derives is not None and wrong != derives:
            drift.append(
                f"the ledger's composed_actions names class {wrong} for "
                f"{action}, which derives composed of class {derives}"
            )
    # B6/R1 (2026-10-23 folds): the CLASS set joins the drift arithmetic,
    # keyed to the APPLIED classes — the pin-declared classes at least
    # one of whose claims the descriptor declares, exactly the set
    # derive-ui writes (B6, lane B F2: the pre-fold walk discarded the
    # derived class set entirely, so deleting the rows left migrate-ui
    # green and the next family bump re-stamped the family stamps
    # without re-resolving the now-unnamed classes; R1, fold wave 3:
    # keying to the PIN-DECLARED set instead refused drift against a
    # ledger derive-ui had just written for the sanctioned claims-
    # nowhere shape, and the author's re-derive looped on byte-identical
    # output — an unapplied class is the gate's disclosure, never
    # drift). The extra-class direction is normally refused earlier — a
    # class no pin declares fails re-resolution as
    # ``migrate_ui_composed_unresolved`` — so deletion, unapplied
    # hand-adds and malformed rows are where this arithmetic bites; both
    # directions run regardless.
    ledger_class_urns = {str(row["class"]) for row in class_rows}
    derived_class_urns = set(applied_classes)
    for class_urn in sorted(ledger_class_urns - derived_class_urns):
        drift.append(
            f"the ledger's composed_classes names {class_urn}, which "
            "composes no action this descriptor declares"
        )
    for class_urn in sorted(derived_class_urns - ledger_class_urns):
        drift.append(
            f"the descriptor applies composed class {class_urn} but the "
            "ledger's composed_classes omits it"
        )
    if drift:
        raise ValueError(
            "migrate_ui_ledger_drift: the class-reference ledger's "
            "inventories disagree with the current descriptor and pins ("
            + "; ".join(drift[:4])
            + "); re-derive with 'benchweave-sdk derive-ui --force', do not "
            "migrate — nothing was written"
        )
    new = raw
    lines: list[str] = []
    if cv != target or rv != target:
        for key, value in (("contract_version", cv), ("reference_version", rv)):
            if value == target:
                continue
            new, count = _restamp(new, key=key, old=value, new=target)
            if count == 0:
                raise ValueError(
                    f"migrate_ui_stamp_unlocatable: ui/class-reference.json: "
                    f"the {key} pattern for {value!r} is not present in the "
                    "raw bytes; migrate-ui re-stamps bytes in place, it "
                    "never re-serializes"
                )
        moved = [
            f"{key} {value} -> {target}"
            for key, value in (("contract_version", cv), ("reference_version", rv))
            if value != target
        ]
        # N4 (2026-10-23 fold): the line names exactly the stamps that
        # moved, each with its own old value — a summary keyed on
        # ``contract_version`` printed "0.4.0 -> 0.4.0" when only
        # ``reference_version`` had moved.
        lines.append(
            "migrated ui/class-reference.json: plugin-ui-class-reference "
            + ", ".join(moved)
        )
    stale_validations = [
        row for row in class_rows if row["validated_against"] != target
    ]
    if stale_validations:
        for value in sorted(
            {row["validated_against"] for row in stale_validations}
        ):
            new, count = _restamp(
                new, key="validated_against", old=value, new=target
            )
            if count == 0:
                raise ValueError(
                    f"migrate_ui_stamp_unlocatable: ui/class-reference.json: "
                    f"the validated_against pattern for {value!r} is not "
                    "present in the raw bytes; migrate-ui re-stamps bytes in "
                    "place, it never re-serializes"
                )
        lines.append(
            f"re-stamped {len(stale_validations)} "
            "composed_classes[].validated_against to "
            f"{target} (each re-resolved and validated under the target)"
        )
    if new == raw:
        return None, []
    return new, lines


def migrate_ui(
    envelope_path: Path,
    descriptor_path: Path,
    root: Path,
    catalogue_path: Path,
    *,
    firmware: str | None,
    features: frozenset[str],
    panels: frozenset[str],
) -> MigrationOutcome:
    """Re-stamp the plugin-ui contract documents to the lock's active version.

    The migration semantics are a version re-stamp plus the envelope hash
    repair (issue #460; the corpus's own sanctioned migration for the
    plugin-ui family), never re-derivation: the manifest is author-editable
    content under a protected tree, so the migration's diff must be the
    version string and nothing else. The re-stamped set is validated in
    memory through the same vendored validator ``check-ui`` runs (SRF-2's
    one gate) BEFORE any write; a set that does not validate is refused with
    nothing written. The four sequential writes (the three plugin-ui
    documents and the class-reference ledger, #541 slice 2) are not
    atomic — the author's VCS is the recovery, the same disclosed posture
    as ``derive-ui``.

    Parameters
    ----------
    envelope_path, descriptor_path, catalogue_path
        The presentation envelope, the device descriptor and the binding catalogue.
    root
        The package resource root the envelope's paths are relative to.
    firmware
        Firmware version the re-stamped set is judged against, or None.
    features, panels
        What the renderer under test supports; passed to the pre-write
        validation unchanged so ``migrate-ui`` accepts exactly what
        ``check-ui`` with the same flags accepts.

    Returns
    -------
    MigrationOutcome
        ``noop`` when all three documents already carry the active version
        (safe to run in scripts and CI); otherwise one line per changed file
        plus advisory notes, with ``target`` the lock's active plugin-ui.

    Raises
    ------
    ValueError
        ``migrate_ui_ahead:`` when any document orders above the active
        (install the newer SDK; a downgrade write would produce documents the
        newer SDK that authored them no longer validates),
        ``migrate_ui_version_absent:``, ``migrate_ui_stamp_unlocatable:`` or
        ``migrate_ui_invalid_after_stamp:`` (each naming its file; the first
        three before any byte is composed, the last before any byte is
        written); otherwise as ``check_ui``.
    """
    contract = _contract()
    target = active_version("plugin-ui")
    envelope_raw = read_file(envelope_path)
    descriptor_raw = read_file(descriptor_path)
    catalogue_raw = read_file(catalogue_path)
    try:
        envelope = contract.parse_document(envelope_raw)
        resource_root = envelope["resource_root"]
        manifest_path = envelope["manifest"]["path"]
        if not contract.safe_resource_path(resource_root) or not contract.safe_resource_path(
            manifest_path
        ):
            raise ValueError("Unsafe presentation resource path")
    except contract.DocumentError as exc:
        raise ValueError(f"migrate_ui_version_absent: presentation.json: {exc}") from exc
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed presentation resource references") from exc
    base = root / resource_root
    manifest_file = base / manifest_path
    manifest_raw = read_file(manifest_file)
    manifest_label = f"{resource_root}/{manifest_path}"
    # The manifest's declared assets ride the validation set unchanged —
    # the migration never touches asset bytes (the _load_ui_candidate shape).
    resources: dict[str, bytes] = {manifest_path: manifest_raw}
    total = len(manifest_raw)
    raw_by_label = {
        "presentation.json": envelope_raw,
        manifest_label: manifest_raw,
        "binding-catalogue.json": catalogue_raw,
    }
    try:
        manifest = contract.parse_document(manifest_raw)
        assets = manifest.get("assets", [])
        if not isinstance(assets, list) or len(assets) > 256:
            raise ValueError("Asset collection exceeds limit")
        for asset in assets:
            name = asset["path"]
            if not contract.safe_resource_path(name):
                raise ValueError("Unsafe asset path")
            if name not in resources:
                raw = read_file(base / name, min(16 * 1024 * 1024, 64 * 1024 * 1024 - total))
                resources[name] = raw
                total += len(raw)
    except contract.DocumentError as exc:
        raise ValueError(f"migrate_ui_version_absent: {manifest_label}: {exc}") from exc
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed presentation resource references") from exc

    stamps: dict[str, str] = {}
    for label, raw in raw_by_label.items():
        try:
            document = contract.parse_document(raw)
        except contract.DocumentError as exc:
            raise ValueError(f"migrate_ui_version_absent: {label}: {exc}") from exc
        version = document.get("contract_version")
        if not isinstance(version, str) or _tuple_or_none(version) is None:
            raise ValueError(
                f"migrate_ui_version_absent: {label}: no version-shaped "
                f"MAJOR.MINOR.PATCH contract_version ({version!r})"
            )
        stamps[label] = version
    ahead = [
        (label, version)
        for label, version in stamps.items()
        if _tuple(version) > _tuple(target)
    ]
    if ahead:
        label, version = ahead[0]
        raise ValueError(
            f"migrate_ui_ahead: {label} is at plugin-ui {version}, above this SDK's "
            f"active {target}; install the newer SDK that serves {version} — "
            "migrate-ui never writes versions down"
        )
    # #541 slice 2 (standards record §8): the class-reference ledger joins
    # the re-stamp set. Computed and refused BEFORE any byte is written —
    # drift and unresolved classes are derive-ui motions, not version
    # writes — and the plugin-ui noop below no longer short-circuits a
    # stale ledger.
    ledger_file = base / "class-reference.json"
    ledger_new: bytes | None = None
    ledger_lines: list[str] = []
    if ledger_file.is_file():
        ledger_new, ledger_lines = _migrate_classref_ledger(
            ledger_file, descriptor_raw, descriptor_path
        )
    if all(version == target for version in stamps.values()) and ledger_new is None:
        return MigrationOutcome(target=target, noop=True)

    new_by_label: dict[str, bytes] = {}
    for label, raw in raw_by_label.items():
        old = stamps[label]
        if old == target:
            new_by_label[label] = raw
            continue
        new, count = _restamp(raw, key="contract_version", old=old, new=target)
        if count == 0:
            raise ValueError(
                f"migrate_ui_stamp_unlocatable: {label}: the contract_version pattern "
                f"for {old!r} is not present in the raw bytes; migrate-ui re-stamps "
                "bytes in place, it never re-serializes"
            )
        new_by_label[label] = new
    # The hash chain repair: the envelope's manifest.sha256 becomes the hash
    # of the re-stamped manifest bytes — requirement (2) of the issue,
    # mechanized with the same substitution discipline.
    new_hash = hashlib.sha256(new_by_label[manifest_label]).hexdigest()
    stated_hash = envelope["manifest"]["sha256"]
    if not isinstance(stated_hash, str):
        raise ValueError("Malformed presentation resource references")
    if stated_hash != new_hash:
        envelope_new, count = _restamp(
            new_by_label["presentation.json"], key="sha256", old=stated_hash, new=new_hash
        )
        if count == 0:
            raise ValueError(
                "migrate_ui_stamp_unlocatable: presentation.json: the manifest sha256 "
                "pattern cannot be located in the raw bytes; migrate-ui re-stamps "
                "bytes in place, it never re-serializes"
            )
        new_by_label["presentation.json"] = envelope_new

    resources_new = dict(resources)
    resources_new[manifest_path] = new_by_label[manifest_label]
    report = validate_presentation(
        new_by_label["presentation.json"],
        descriptor_raw=descriptor_raw,
        resources=resources_new,
        binding_catalogue=contract.parse_document(new_by_label["binding-catalogue.json"]),
        supported_features=features,
        supported_panels=panels,
        firmware=firmware,
    )
    if not report.valid:
        findings = "; ".join(
            f"{row.code}: {row.path}: {row.message}" for row in report.findings
        )
        raise ValueError(
            "migrate_ui_invalid_after_stamp: the re-stamped set does not validate "
            f"against plugin-ui {target}: {findings}. The findings name changes the "
            "re-stamp does not make (a drifted descriptor needs re-derivation, not "
            "migration); nothing was written"
        )

    lines: list[str] = []
    hash_only = (
        stamps["presentation.json"] == target
        and new_by_label["presentation.json"] != envelope_raw
    )
    for label in ("presentation.json", manifest_label, "binding-catalogue.json"):
        path = {
            "presentation.json": envelope_path,
            manifest_label: manifest_file,
            "binding-catalogue.json": catalogue_path,
        }[label]
        new = new_by_label[label]
        if new == raw_by_label[label]:
            continue
        path.absolute().write_bytes(new)
        line = f"migrated {label}: plugin-ui {stamps[label]} -> {target}"
        if label == "presentation.json" and hash_only:
            line += ", manifest hash repaired"
        lines.append(line)
    if ledger_new is not None:
        # The ledger motion was computed and validated before any write;
        # it lands after the plugin-ui documents, same run, same
        # discipline (version strings only).
        ledger_file.write_bytes(ledger_new)
        lines.extend(ledger_lines)

    return MigrationOutcome(target=target, lines=tuple(lines))


def _write_preview_examples(
    destination: Path, package: str, targets: list[dict[str, Any]], *, with_plot: bool
) -> None:
    # Body import: the example generator moved to ``fixtures`` so the
    # regen-fixtures command reaches it (issue #463 row 8), and that module
    # imports this one at module level — the reverse import must be
    # call-time (the same posture the classref import below uses). Same
    # function, same bytes: scaffold and regen share ONE generator.
    from .fixtures import _preview_fixture

    # The generated conformance test asserts the projection outcome the
    # scaffold actually produced: a plot example when a numeric observation
    # target exists, its documented absence when none does.
    plot_assert = (
        '    assert model.plot_views, "the scaffold plot must project"'
        if with_plot
        else (
            '    assert model.plot_views == (), '
            '"no numeric observation target means no example plot"'
        )
    )
    fixtures = destination / "src" / package / "ui" / "fixtures"
    fixtures.mkdir()
    for filename, severity in (("normal", "neutral"), ("warning", "warning")):
        document = _preview_fixture(targets[0], suffix=filename, severity=severity)
        fixture = fixtures / f"{filename}.json"
        fixture.write_bytes((json.dumps(document, indent=2) + "\n").encode("utf-8"))
    lines = [
        '"""Generated offline presentation-preview conformance smoke test."""',
        "",
        "from importlib.resources import files",
        "from pathlib import Path",
        "",
        "from benchweave_sdk.fixtures import BASELINE_IDS, build_preview_model",
        "from benchweave_sdk.presentation import load_validated_preview_inputs",
        "",
        "",
        "def _materialise(source, destination: Path) -> None:",
        "    destination.mkdir(parents=True, exist_ok=True)",
        "    for entry in source.iterdir():",
        "        if entry.is_dir():",
        "            _materialise(entry, destination / entry.name)",
        "        else:",
        "            (destination / entry.name).write_bytes(entry.read_bytes())",
        "",
        "def test_presentation_preview_contract(tmp_path: Path) -> None:",
        f'    package = tmp_path / "{package}"',
        f'    _materialise(files("{package}"), package)',
        "    candidate = load_validated_preview_inputs(",
        '        package / "presentation.json",',
        '        package / "descriptor.json",',
        "        package,",
        '        package / "binding-catalogue.json",',
        "        firmware=None,",
        "        features=frozenset(),",
        "        panels=frozenset(),",
        "    )",
        "    model = build_preview_model(candidate)",
        "    scenarios = model.scenarios",
        "    assert BASELINE_IDS <= {row.id for row in scenarios}",
        plot_assert,
        "",
    ]
    test_path = destination / "tests" / "test_presentation_preview.py"
    test_path.write_bytes(("\n".join(lines)).encode("utf-8"))


def _ui_targets(descriptor: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive presentation targets, rejecting unsupported descriptor types."""
    types = {"float": "number", "int": "integer", "bool": "boolean", "string": "string"}
    targets: list[dict[str, Any]] = []
    for parameter in descriptor["parameters"]:
        if parameter["access"] not in ("ro", "rw"):
            continue
        name = parameter["name"]
        variable_type = types.get(str(parameter["type"]))
        if variable_type is None:
            raise ValueError(
                f"preview_unsupported_parameter_type: {name}: {parameter['type']}"
            )
        targets.append(
            {
                "id": name,
                "kind": "observation",
                "parameter_id": name,
                "variables": [
                    {
                        "id": "value",
                        "type": variable_type,
                        "unit": parameter.get("unit"),
                        "shape": "scalar",
                        "axis_role": "value",
                    }
                ],
            }
        )
    return targets


def create_ui_resources(destination: Path, package: str) -> list[dict[str, str]]:
    """Add presentation resources to an already generated SDK starter.

    A class-conformant descriptor (one whose profiles match a vendored
    ``plugin-ui-class-reference`` document) derives through the class
    expander — the full reference-shaped presentation set, the preset
    scaffolds and the birth conformance declaration. Everything else takes
    the legacy read-only-observations path. Returns the reference's
    ``cannot_derive`` rows (empty on the legacy path) so the caller can
    print them; successful scaffolding is never admission or approval to
    apply settings."""
    root = destination / "src" / package
    raw = read_file(root / "descriptor.json")
    descriptor = _contract().parse_document(raw)
    # The class-reference path first: the reference is the presentation
    # authority for a class-conformant descriptor, whether or not the
    # descriptor also carries readable parameters. (Body import: classref
    # reads back through this module's read_file, so a module-level import
    # would be a cycle.)
    from .classref import derive_ui, find_reference

    references = [
        reference
        for profile in descriptor.get("profiles") or []
        if (reference := find_reference(str(profile))) is not None
    ]
    if references:
        derived = derive_ui(raw, references[0], descriptor_path=root / "descriptor.json")

        def raw_bytes(document: object) -> bytes:
            return (json.dumps(document, indent=2) + "\n").encode()

        ui = root / "ui"
        ui.mkdir(exist_ok=True)
        (ui / "manifest.json").write_bytes(raw_bytes(derived.manifest))
        (root / "presentation.json").write_bytes(raw_bytes(derived.envelope))
        (root / "binding-catalogue.json").write_bytes(raw_bytes(derived.catalogue))
        settings = ui / "settings"
        settings.mkdir(exist_ok=True)
        (settings / "configure.schema.json").write_bytes(
            raw_bytes(derived.settings_schema)
        )
        presets = ui / "presets"
        presets.mkdir(exist_ok=True)
        for slug, scaffold in derived.preset_scaffolds.items():
            (presets / f"{slug}.json").write_bytes(raw_bytes(scaffold))
        (ui / "class-reference.json").write_bytes(raw_bytes(derived.declaration))
        return list(derived.cannot_derive)
    descriptor_hash = hashlib.sha256(raw).hexdigest()
    # Validate everything derivable before the first write so a rejected
    # descriptor leaves no half-generated project behind.
    targets = _ui_targets(descriptor)
    if not targets:
        raise ValueError("UI scaffolding requires at least one readable descriptor parameter")
    bindings = [{"id": row["id"], "kind": "observation", "target_id": row["id"]} for row in targets]
    # Every new plugin ships a working plot example: the first NUMERIC
    # observation target — the same number/integer test the presentation
    # validator applies to plot axes — gains the receipt-time axis a valid
    # time-series plot requires (exactly the {receipt_time, value} shape the
    # contract admits), and the readings page declares one hinted plot over
    # it. Pinning the example to targets[0] shipped a plot check-ui rejects
    # whenever a bool/string parameter sorts first (_ui_targets admits them;
    # _plot_findings refuses non-numeric axes). A descriptor with no numeric
    # observation target gets no example plot — a disclosed degradation, not
    # a refusal.
    plot_index = next(
        (
            index
            for index, row in enumerate(targets)
            if row["variables"][0]["type"] in ("number", "integer")
        ),
        None,
    )
    plots: list[dict[str, Any]] = []
    if plot_index is not None:
        targets[plot_index]["variables"].insert(
            0,
            {
                "id": "time",
                "type": "number",
                "unit": "s",
                "shape": "scalar",
                "axis_role": "receipt_time",
            },
        )
        plots.append(
            {
                "kind": "time_series",
                "binding_id": bindings[plot_index]["id"],
                "x": "time",
                "y": ["value"],
                "channel_hints": [{"variable_id": "value", "color_role": "muted"}],
            }
        )
    readings_page: dict[str, Any] = {
        "id": "readings",
        "title": "Readings",
        "kind": "readings",
        "bindings": [row["id"] for row in bindings],
        "required": True,
    }
    if plots:
        readings_page["plots"] = plots
    manifest = {
        # The lock's active plugin-ui version (issue #221): derived,
        # never stated — the three generated documents stamp the family
        # they validate against.
        "contract_version": active_version("plugin-ui"),
        "plugin_id": descriptor["id"],
        "descriptor_sha256": descriptor_hash,
        "bindings": bindings,
        "pages": [readings_page],
    }
    manifest_raw = (json.dumps(manifest, indent=2) + "\n").encode()
    envelope = {
        "contract_version": active_version("plugin-ui"),
        "descriptor_sha256": descriptor_hash,
        "resource_root": "ui",
        "manifest": {"path": "manifest.json", "sha256": hashlib.sha256(manifest_raw).hexdigest()},
    }
    catalogue = {
        "contract_version": active_version("plugin-ui"),
        "descriptor_sha256": descriptor_hash,
        "targets": targets,
    }
    (root / "ui").mkdir()
    (root / "ui/manifest.json").write_bytes(manifest_raw)
    for name, document in (("presentation.json", envelope), ("binding-catalogue.json", catalogue)):
        (root / name).write_bytes((json.dumps(document, indent=2) + "\n").encode("utf-8"))
    _write_preview_examples(destination, package, targets, with_plot=plot_index is not None)
    (destination / "UI-GUIDE.md").write_text(
        "# Optional plugin presentation\n\n"
        "The starter declares read-only observations. It adds no device actions.\n"
        f"The project root contains pyproject.toml, AI-GUIDE.md, this guide and tests/.\n"
        f"Its Python package is src/{package}/. Presentation files are laid out as:\n\n"
        f"```text\nsrc/{package}/\n"
        "  descriptor.json\n  presentation.json\n  binding-catalogue.json\n"
        "  ui/\n    manifest.json\n"
        "    fixtures/  # generated synthetic preview examples\n"
        "    settings/  # author-supplied schemas, when configuration exists\n"
        "    presets/   # author-supplied complete configurations\n"
        "    assets/    # author-supplied declared static resources\n```\n\n"
        "The SDK generates ui/manifest.json and schema-valid examples in ui/fixtures/.\n"
        "Run `benchweave-sdk regen-fixtures <project>` to write the two examples\n"
        "again after you edit the binding catalogue.\n"
        "Add settings/ and presets/ only for configuration actions the descriptor implements.\n"
        "Keep resources inside the Python package so they ship in the wheel.\n"
        "Keep collected data, credentials and deployment configuration outside it.\n\n"
        f"Run from the project root: `benchweave-sdk check-ui src/{package}/presentation.json "
        f"--descriptor src/{package}/descriptor.json --resources src/{package} "
        f"--catalogue src/{package}/binding-catalogue.json`.\n"
        "When a new SDK release moves the active plugin-ui version,\n"
        "`benchweave-sdk migrate-ui` re-stamps the three presentation documents and\n"
        "takes the same arguments as check-ui.\n\n"
        "--resources names the package root; the envelope selects resource_root=ui.\n"
        "Manifest asset paths are relative to ui/, for example presets/default.json.\n"
        "Use canonical paths without symlink components. Keep the binding catalogue\n"
        "aligned with the descriptor and update exact byte hashes after edits.\n\n"
        "A manifest `assets[]` row whose `path` is exactly `preview.css` restyles\n"
        "the preview pages. Put the file at\n"
        f"`src/{package}/ui/preview.css`, beside ui/manifest.json. The row\n"
        "path is relative to ui/, the resource root. Do not put the file\n"
        "under ui/assets/. The row also declares the `sha256` digest of the\n"
        "file bytes, and the host checks the digest again at serve time. The\n"
        "file can be 64 KiB at most. The override serves on the standalone\n"
        "host only, and the gateway never serves a plugin stylesheet\n"
        "override. A refused override gives the prefix\n"
        "`standalone_preview_override_refused:`, and the page carries the\n"
        "marker `data-bw-override-refused` while the default tokens render.\n"
        "The user guide covers the override in\n"
        "section \"The plugin stylesheet override (preview.css)\".\n\n"
        f"Preview with: `benchweave-sdk preview-ui .` from the project root "
        f"(the standalone host on the scripted mock transport; needs the "
        f"`benchweave-sdk[server]` extra).\n\n"
        "All preview values and receipts are simulated. check-ui and preview-ui are not\n"
        "admission, hardware qualification or permission to operate hardware.\n"
        "Declared manifest plots and channel hints render in the preview; plot values\n"
        "are per-scenario snapshots (one simulated value per observed target), not history.\n"
        "A descriptor with no numeric observation target ships no example plot.\n"
        "Preset selection performs no I/O. Applying settings requires a separately\n"
        "approved procedure. Acquisition and retained observations belong to the gateway.\n",
        encoding="utf-8",
        newline="\n",
    )
    return []
