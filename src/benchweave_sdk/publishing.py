"""Deterministic, keyless submission packaging for the publishing lane (CR-1..CR-6).

``benchweave-sdk package`` builds the single generated artefact set for a
finished plugin — release manifest, payload archive, and the submission
metadata (publish-record draft) — deterministically: canonical JSON, ZIP_STORED
members with fixed timestamps, sorted members, no clock, no key, no network
(the ``publish_dev``/``registry_common`` discipline re-implemented SDK-side;
the gateway's builder is never imported — REG-4's read-not-import posture —
and agreement between the two builders is pinned gateway-side by a parity
test).

Entry gates (PRD §5(l) increment-1 criteria), each a stable machine prefix:

- ``dev_lineage_refused:`` (CR-35) — any dependency whose registry id is
  dev-prefixed refuses; dev-unsigned lineage never reaches a submission.
- ``source_ref_mutable:`` (CR-36) — the source linkage must be a commit digest
  (40-hex SHA-1 or 64-hex SHA-256). Deliberately stricter than gateway
  admission's four-name denylist: any moving name refuses here.
- ``capability_declaration_absent:`` (CR-45) — the closed three-way capability
  enumeration (all-false is an explicit none); absence is unrepresentable in a
  finished package. Enforcement is deploy-policy only (Q13).
- ``transport_triples_absent:`` (CR-49) — a descriptor declaring a transport
  provider must publish its admitted contract triples. Detection is
  conservative: any pinned contract id or required feature in a
  ``otdp.transport`` namespace counts as a declaration; the authoritative
  provider-admission check lives gateway-side (issue #147's provider rows).
- ``firmware_provenance_absent:`` (CR-50) — a payload bundling ``firmware/``
  without vendor attestation pinned against a vendor manifest refuses.
- ``closure_diff_absent:`` (CR-38) — the submission's publish-record draft
  must carry the dependency closure diff versus the prior release.

Namespace gates (CR-15/CR-16/CR-39) run against a clone of the registry
repository (``records/publishers.json`` + ``lane-rules.json`` + ``releases/``):
``namespace_collision:``, ``namespace_reserved:`` and ``namespace_lookalike:``
under the committed similarity rule.

Missing components refuse naming the component (CR-1, ``component_absent:``).
The builder is keyless: it writes no signature, and nothing here loads the
signing stack — the lane's signatures are maintainer-side.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

#: The CR-1 artefact-component set. One definition in three committed places —
#: here, the publishing docs' artefact block, and the registry lane's records
#: schema (review.components enum) — pinned equal by the registry repository's
#: enumeration CI (A2). A submission missing any component refuses naming it.
REQUIRED_COMPONENTS: tuple[str, ...] = (
    "adapter-source",
    "build-provenance",
    "capability-declaration",
    "closure-diff",
    "conformance-evidence",
    "dependency-lock",
    "descriptor",
    "licence",
    "payload-inventory",
    "release-manifest",
)

#: The submission manifest's schema version. The submission form is the 0.1.1
#: shape (valid under the 0.1.2 enum arm); the review block is inserted at
#: signing time, which flips the version to 0.1.2 — maintainer-side.
MANIFEST_SCHEMA_VERSION = "0.1.1"

#: Submission metadata shape version (not a corpus version).
SUBMISSION_VERSION = 1

FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
DEFAULT_RELEASED_AT = "2026-10-01T00:00:00Z"

_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_IMMUTABLE_REVISION = re.compile(r"^([a-f0-9]{40}|[a-f0-9]{64})$")
_PACKAGE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9_-]*$")

#: Payload member basename -> manifest role. Unlisted names refuse
#: (``component_absent`` family) rather than shipping an unroleable entry.
ROLE_BY_BASENAME: dict[str, str] = {
    "LICENSE": "licence",
    "CHANGELOG.md": "documentation",
    "MIGRATION.md": "documentation",
    "README.md": "documentation",
    "protocol-evidence.md": "documentation",
    "descriptor.json": "descriptor",
    "lock.json": "dependency_lock",
    "constraints.json": "schema",
    "sbom.json": "sbom",
    "build-provenance.json": "build_provenance",
    "dependency-lock.json": "dependency_lock",
}
_ROLE_BY_SUFFIX: tuple[tuple[str, str], ...] = (
    (".py", "implementation"),
    (".md", "documentation"),
)


class PublishingError(ValueError):
    """Packaging refused; the message carries a stable machine prefix."""


def canonical_bytes(obj: object) -> bytes:
    """Canonical JSON: sorted keys, compact separators, LF, trailing newline."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def zip_bytes(members: list[tuple[str, bytes]]) -> bytes:
    """ZIP_STORED throughout: zlib-independent reproducibility."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as archive:
        for path, data in sorted(members):
            info = zipfile.ZipInfo(path, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return buf.getvalue()


def closure_digest_of_dependencies(dependencies: list[dict[str, Any]]) -> str:
    """CR-38's closure digest: sha256 over the canonical sorted dependency pins.

    The same definition the registry lane's validity checker uses, so a
    sign-off can never cover a different closure than the one published.
    """
    pins = sorted(
        (dep["registry_id"], dep["package_id"], dep["version"], dep["manifest_sha256"])
        for dep in dependencies
    )
    return sha256_hex(canonical_bytes(pins))


# --- namespace hygiene (CR-15/CR-16/CR-39) -------------------------------------


@dataclass(frozen=True)
class LaneRules:
    """The committed lane rules a packaging run checks against."""

    reserved_namespaces: frozenset[str]
    reserved_plugins: frozenset[str]
    similarity_max_distance: int
    confusables: dict[str, str]
    dev_prefix: str = "dev-"
    #: Q15's tier rule: the publishers with a RECORDED provider admission,
    #: the only ones who may publish a scoped_transport-declaring release
    #: without publishing its admitted contract triples (the transport lane
    #: is unbound, so this list is empty until #167 activates it).
    transport_admissions: frozenset[str] = frozenset()

    @classmethod
    def load(cls, registry_clone: Path) -> LaneRules:
        rules = json.loads((registry_clone / "lane-rules.json").read_bytes())
        params = rules["similarity_rule"]["params"]
        tier = rules.get("transport_tier_rule", {})
        return cls(
            reserved_namespaces=frozenset(rules["namespace_rules"]["reserved_namespaces"]),
            reserved_plugins=frozenset(rules["namespace_rules"]["reserved_plugins"]),
            similarity_max_distance=int(params["max_edit_distance"]),
            confusables=dict(params["confusable_map"]),
            dev_prefix=str(rules["namespace_rules"]["dev_registry_prefix"]),
            transport_admissions=frozenset(tier.get("admissions", [])),
        )


def _skeleton(name: str, rules: LaneRules) -> str:
    """Fold a name to its confusable skeleton (lowercase, separators out)."""
    folded = name.casefold()
    for separator in ("-", "_", ".", "/"):
        folded = folded.replace(separator, "")
    for source, target in sorted(rules.confusables.items(), key=lambda kv: -len(kv[0])):
        folded = folded.replace(source, target)
    return folded


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (left_char != right_char),  # substitution
                )
            )
        previous = current
    return previous[-1]


def check_namespace(
    package_id: str,
    rules: LaneRules,
    existing_namespaces: set[str],
    existing_package_owners: dict[str, set[str]],
) -> list[str]:
    """Refuse or flag a package id under the committed namespace rules.

    Collisions are PER-AUTHOR (owner ruling, issue #223 fold): a publisher's
    own next version of an existing package id is NOT a collision — it routes
    to the closure-diff-versus-prior path; the exact id claimed by a
    different recorded owner still collides; and two different authors may
    register the same device (plugin) NAME under their own namespaces. The
    similarity rule flags lookalikes for human review; reserved names and
    cross-owner collisions refuse.
    """
    findings: list[str] = []
    if _PACKAGE_ID.fullmatch(package_id) is None:
        findings.append(f"namespace_invalid:{package_id}")
        return findings
    publisher, plugin = package_id.split("/", 1)
    if publisher in rules.reserved_namespaces:
        findings.append(f"namespace_reserved:{publisher}")
    if plugin in rules.reserved_plugins:
        findings.append(f"namespace_reserved:{plugin}")
    owners = existing_package_owners.get(package_id, set())
    if owners and publisher not in owners:
        findings.append(f"namespace_collision:{package_id}")
    # CR-39: the publisher segment is compared against existing namespaces;
    # the full id against existing packages — a lookalike is flagged for human
    # review, never silently admitted.
    publisher_skeleton = _skeleton(publisher, rules)
    for existing in sorted(existing_namespaces):
        if existing == publisher:
            continue
        distance = _edit_distance(publisher_skeleton, _skeleton(existing, rules))
        if 0 < distance <= rules.similarity_max_distance:
            findings.append(f"namespace_lookalike:{publisher}~{existing}:{distance}")
    package_skeleton = _skeleton(package_id, rules)
    for existing in sorted(existing_package_owners):
        if existing == package_id:
            continue
        distance = _edit_distance(package_skeleton, _skeleton(existing, rules))
        if 0 < distance <= rules.similarity_max_distance:
            findings.append(f"namespace_lookalike:{package_id}~{existing}:{distance}")
    return findings


# --- descriptor reading ---------------------------------------------------------


def _package_dir(plugin_dir: Path) -> Path:
    """The plugin's source package directory, discovered not assumed.

    Real plugin trees carry the full dist name (``benchweave_fnirsi_dps150``),
    not the directory-derived short form, so the package directory is found by
    glob under ``src/`` and falls back to the plugin root.
    """
    if plugin_dir.name.startswith("benchweave_"):
        return plugin_dir
    candidates = sorted((plugin_dir / "src").glob("benchweave_*"))
    for candidate in candidates:
        if (candidate / "descriptor.json").is_file() or sorted(candidate.glob("*.py")):
            return candidate
    return plugin_dir


def _find_descriptor(plugin_dir: Path) -> Path:
    candidates = [
        _package_dir(plugin_dir) / "descriptor.json",
        plugin_dir / "descriptor.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise PublishingError("component_absent:descriptor (no descriptor.json in the plugin tree)")


def _declares_transport_provider(descriptor: dict[str, Any]) -> bool:
    """Conservative transport-provider detection (CR-49), both forms.

    A pinned contract id or required feature in an ``otdp.transport``
    namespace counts, and so does the ``scoped_transport`` permission in the
    adapter block: the tier rule (Q15) governs who may HOLD that permission,
    so declaring it without either published triples or a recorded provider
    admission refuses. The authoritative provider-admission check is
    gateway-side (issue #147); this publish gate errs toward demanding the
    evidence.
    """
    for contract in descriptor.get("contracts", []) or []:
        if str(contract.get("id", "")).startswith("otdp.transport"):
            return True
    for feature in descriptor.get("required_features", []) or []:
        if str(feature).startswith("otdp.transport"):
            return True
    permissions = (
        descriptor.get("integration", {}).get("adapter", {}).get("permissions", []) or []
    )
    return "scoped_transport" in permissions


# --- the entry gates -------------------------------------------------------------


def _gate_source_revision(revision: str) -> None:
    if _IMMUTABLE_REVISION.fullmatch(revision) is None:
        raise PublishingError(
            f"source_ref_mutable: {revision!r} is not a commit digest "
            "(40-hex SHA-1 or 64-hex SHA-256); moving names refuse at publish "
            "even where gateway admission would admit them (CR-36)"
        )


def _gate_dev_lineage(dependencies: list[dict[str, Any]], dev_prefix: str) -> None:
    for dep in dependencies:
        if str(dep.get("registry_id", "")).startswith(dev_prefix):
            raise PublishingError(
                f"dev_lineage_refused: dependency {dep['package_id']!r} resolves "
                f"through dev-unsigned origin {dep['registry_id']!r}; no dev-prefixed "
                "registry id can reach a submission (CR-35)"
            )


def _gate_capability(declaration: dict[str, bool] | None) -> None:
    expected = {
        "network_egress",
        "subprocess_or_native_library",
        "filesystem_writes_beyond_evidence_retention",
    }
    if declaration is None or set(declaration) != expected or not all(
        isinstance(declaration[key], bool) for key in expected
    ):
        raise PublishingError(
            "capability_declaration_absent: the closed three-way capability "
            "enumeration (network_egress, subprocess_or_native_library, "
            "filesystem_writes_beyond_evidence_retention; all-false is an "
            "explicit none) is required — absence is unrepresentable in a "
            "finished package (CR-45)"
        )


def _gate_transport_triples(
    descriptor: dict[str, Any],
    transport_triples: tuple[dict[str, str], ...],
    publisher: str,
    rules: LaneRules,
) -> None:
    if not _declares_transport_provider(descriptor):
        return
    if transport_triples:
        return
    if publisher in rules.transport_admissions:
        return
    raise PublishingError(
        "transport_triples_absent: the descriptor declares a transport "
        "provider (an otdp.transport contract, or the scoped_transport "
        "permission); publish the admitted contract triples (id, version, "
        "sha256) it intends to drive, or hold a recorded provider admission "
        "in the lane rules (CR-49, Q15)"
    )


def _gate_firmware(
    members: list[tuple[str, bytes]], attestation: dict[str, Any] | None
) -> None:
    bundles_firmware = any(path.startswith("firmware/") for path, _data in members)
    if not bundles_firmware:
        return
    if attestation is None:
        raise PublishingError(
            "firmware_provenance_absent: the payload bundles firmware/ without "
            "vendor attestation pinned against a vendor manifest — the "
            "publisher's own signature alone does not carry firmware "
            "provenance (CR-50)"
        )
    # Owner ruling (issue #223 rework): attested firmware is STATED, never
    # refused here — enforcement is the client's decision. The registry
    # payload-role enum carries no firmware role (registry-specification §4),
    # so the bytes stay vendor-distributed (never bundled; a future role is an
    # owner-call standards bump) and the attestation is recorded in the
    # submission draft for the records and the index to advertise.


# --- payload assembly -------------------------------------------------------------


def _role_for(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    if base in ROLE_BY_BASENAME:
        return ROLE_BY_BASENAME[base]
    for suffix, role in _ROLE_BY_SUFFIX:
        if base.endswith(suffix):
            return role
    raise PublishingError(f"component_absent:role-for:{path} (no manifest payload role)")


def _payload_block(zip_data: bytes, members: list[tuple[str, bytes]]) -> dict[str, Any]:
    return {
        "sha256": sha256_hex(zip_data),
        "bytes": len(zip_data),
        "media_type": "application/zip",
        "files": [
            {
                "path": path,
                "role": _role_for(path),
                "bytes": len(data),
                "sha256": sha256_hex(data),
            }
            for path, data in sorted(members)
        ],
    }


def _read_package_dir(plugin_dir: Path) -> tuple[str, list[tuple[str, bytes]]]:
    """Collect the plugin tree's payload members with fixed archive paths."""
    package_dir = _package_dir(plugin_dir)
    members: list[tuple[str, bytes]] = []
    for source in sorted(package_dir.glob("*.py")):
        members.append((f"plugin/{source.name}", source.read_bytes()))
    if not members:
        raise PublishingError("component_absent:adapter-source (no plugin sources found)")
    descriptor = _find_descriptor(plugin_dir)
    members.append(("descriptors/descriptor.json", descriptor.read_bytes()))
    for firmware in sorted((package_dir / "firmware").rglob("*")):
        if firmware.is_file():
            members.append(
                (f"firmware/{firmware.relative_to(package_dir / 'firmware').as_posix()}",
                 firmware.read_bytes())
            )
    contracts_dir = plugin_dir / "contracts"
    if contracts_dir.is_dir():
        for contract in sorted(contracts_dir.iterdir()):
            if contract.is_file():
                members.append((f"contracts/{contract.name}", contract.read_bytes()))
    evidence = _find_evidence(plugin_dir)
    members.append(("evidence/protocol-evidence.md", evidence.read_bytes()))
    licence = _find_licence(plugin_dir)
    members.append(("LICENSE", licence.read_bytes()))
    readme = plugin_dir / "README.md"
    if readme.is_file():
        members.append(("README.md", readme.read_bytes()))
    return package_dir.name, members


def _find_evidence(plugin_dir: Path) -> Path:
    for candidate in (
        plugin_dir / "docs" / "protocol-evidence.md",
        plugin_dir / "docs" / "evidence.md",
        plugin_dir / "EVIDENCE.md",
    ):
        if candidate.is_file():
            return candidate
    raise PublishingError(
        "component_absent:conformance-evidence (no docs/protocol-evidence.md, "
        "docs/evidence.md or EVIDENCE.md in the plugin tree)"
    )


def _find_licence(plugin_dir: Path) -> Path:
    for candidate in (plugin_dir / "LICENSE", plugin_dir / "LICENSE.md", plugin_dir / "LICENCE"):
        if candidate.is_file():
            return candidate
    raise PublishingError("component_absent:licence (no LICENSE file in the plugin tree)")


def _generated_members(
    dependencies: list[dict[str, Any]], plugin_name: str
) -> list[tuple[str, bytes]]:
    """The deterministic generated extras every implementation carries."""
    return [
        ("sbom.json", canonical_bytes({"sbom_version": "1", "components": sorted(
            dep["package_id"] for dep in dependencies
        )})),
        (
            "build-provenance.json",
            canonical_bytes(
                {
                    "inputs": sorted(dep["package_id"] for dep in dependencies),
                    "toolchain": "benchweave-sdk package",
                    "output": "payload.zip",
                    "plugin": plugin_name,
                }
            ),
        ),
        ("dependency-lock.json", canonical_bytes({"lock_version": "1", "dependencies": sorted(
            (dep["registry_id"], dep["package_id"], dep["version"]) for dep in dependencies
        )})),
        ("CHANGELOG.md", b"# Changelog\n\n- initial packaging-lane release\n"),
        ("MIGRATION.md", b"# Migration\n\nNone.\n"),
    ]


# --- prior-release closure diff (CR-38) ------------------------------------------


def _prior_release(
    registry_clone: Path, registry_id: str, package_id: str, version: str
) -> tuple[str, list[dict[str, Any]]] | None:
    """The latest other published release as (version, dependencies), or None."""
    origin = registry_clone / "releases" / registry_id
    if not origin.is_dir():
        return None
    publisher, plugin = package_id.split("/", 1)
    candidates: list[tuple[tuple[int, ...], str, Path]] = []
    for manifest_path in sorted((origin / publisher / plugin).glob("*/manifest.json")):
        release_version = manifest_path.parent.name
        if release_version == version or _VERSION_PATTERN.fullmatch(release_version) is None:
            continue
        candidates.append(
            (
                tuple(int(part) for part in release_version.split(".")),
                release_version,
                manifest_path,
            )
        )
    if not candidates:
        return None
    _key, latest_version, latest_path = max(candidates)
    manifest = json.loads(latest_path.read_bytes())
    return latest_version, list(manifest.get("dependencies", []))


def _closure_diff(
    dependencies: list[dict[str, Any]],
    prior: tuple[str, list[dict[str, Any]]] | None,
) -> dict[str, Any]:
    """CR-38: dependencies added/changed/removed versus the prior release."""
    current_pins = {(dep["registry_id"], dep["package_id"]): dep for dep in dependencies}
    if prior is None:
        return {
            "prior": None,
            "added": sorted(package for _rid, package in current_pins),
            "changed": [],
            "removed": [],
        }
    prior_version, prior_deps = prior
    prior_pins = {(dep["registry_id"], dep["package_id"]): dep for dep in prior_deps}
    return {
        "prior": {"version": prior_version},
        "added": sorted(
            package for rid, package in current_pins if (rid, package) not in prior_pins
        ),
        "changed": sorted(
            package
            for rid, package in current_pins.keys() & prior_pins.keys()
            if current_pins[(rid, package)] != prior_pins[(rid, package)]
        ),
        "removed": sorted(
            package for rid, package in prior_pins if (rid, package) not in current_pins
        ),
    }


# --- the builder -------------------------------------------------------------------


@dataclass
class SubmissionArtifacts:
    """The generated artefact set; every value is canonical/deterministic."""

    manifest: dict[str, Any] = field(default_factory=dict)
    manifest_bytes: bytes = b""
    payload_bytes: bytes = b""
    submission: dict[str, Any] = field(default_factory=dict)
    submission_bytes: bytes = b""
    #: CR-39's similarity flags: lookalikes are FLAGGED for the reviewer,
    #: never silently admitted and never silently dropped. They ride the
    #: submission draft (``namespace_lookalikes``) so the review consults them.
    lookalikes: list[str] = field(default_factory=list)

    def write(self, out: Path) -> list[Path]:
        out.mkdir(parents=True, exist_ok=True)
        written = [
            out / "manifest.json",
            out / "payload.zip",
            out / "submission.json",
        ]
        written[0].write_bytes(self.manifest_bytes)
        written[1].write_bytes(self.payload_bytes)
        written[2].write_bytes(self.submission_bytes)
        return written


def build_submission(
    plugin_dir: Path,
    *,
    registry_clone: Path,
    source_url: str,
    revision: str,
    publisher: str,
    plugin: str | None = None,
    version: str | None = None,
    capability_declaration: dict[str, bool] | None = None,
    dependencies: list[dict[str, Any]] | None = None,
    transport_triples: tuple[dict[str, str], ...] = (),
    firmware_attestation: dict[str, Any] | None = None,
    licence_spdx: str = "MIT",
    released_at: str = DEFAULT_RELEASED_AT,
) -> SubmissionArtifacts:
    """Build the submission artefact set, or refuse with a stable prefix.

    Every manifest pin derives from the plugin's own tree; the builder reads
    no clock and writes nothing until the whole set is built in memory.
    """
    resolved = plugin_dir.resolve()
    if not resolved.is_dir():
        raise PublishingError(f"plugin directory not found: {plugin_dir.as_posix()}")
    plugin_name = plugin or resolved.name
    package_id = f"{publisher}/{plugin_name}"
    if _PACKAGE_ID.fullmatch(package_id) is None:
        raise PublishingError(f"namespace_invalid:{package_id}")

    rules = LaneRules.load(registry_clone)
    _gate_source_revision(revision)
    deps = list(dependencies or [])
    _gate_dev_lineage(deps, rules.dev_prefix)
    _gate_capability(capability_declaration)
    descriptor = json.loads(_find_descriptor(resolved).read_bytes())
    _gate_transport_triples(descriptor, transport_triples, publisher, rules)

    publishers = json.loads((registry_clone / "records" / "publishers.json").read_bytes())
    existing_namespaces = {entry["namespace"] for entry in publishers["publishers"]}
    existing_package_owners = _existing_package_owners(registry_clone)
    findings = check_namespace(
        package_id, rules, existing_namespaces - {publisher}, existing_package_owners
    )
    collisions = [f for f in findings if not f.startswith("namespace_lookalike:")]
    if collisions:
        raise PublishingError("; ".join(collisions))
    lookalikes = sorted(f for f in findings if f.startswith("namespace_lookalike:"))

    package_dir_name, tree_members = _read_package_dir(resolved)
    _gate_firmware(tree_members, firmware_attestation)
    firmware_members = [m for m in tree_members if m[0].startswith("firmware/")]
    if firmware_members and firmware_attestation is not None:
        # Owner ruling (issue #223 rework): attested firmware is stated, not
        # enforced — and never bundled (the payload-role enum carries no
        # firmware role). The bytes stay vendor-distributed; the exclusion is
        # recorded in the draft alongside the attestation.
        tree_members = [m for m in tree_members if not m[0].startswith("firmware/")]
        firmware_attestation = {
            **firmware_attestation,
            "bytes": "vendor-distributed",
            "files": sorted(name for name, _data in firmware_members),
        }
    members = tree_members + _generated_members(deps, package_dir_name)

    pyproject = resolved / "pyproject.toml"
    release_version = version or _pyproject_version(pyproject) or "0.0.0"
    if _VERSION_PATTERN.fullmatch(release_version) is None:
        raise PublishingError(f"version {release_version!r} is not strict numeric semver (X.Y.Z)")

    registry_id = _registry_id(registry_clone)
    prior = _prior_release(registry_clone, registry_id, package_id, release_version)
    closure = _closure_diff(deps, prior)
    closure_digest = closure_digest_of_dependencies(deps)

    payload_zip = zip_bytes(members)
    adapter = descriptor.get("integration", {}).get("adapter", {})
    identity = descriptor.get("identity", {})
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_SCHEMA_VERSION,
        "registry_id": registry_id,
        "package_id": package_id,
        "version": release_version,
        "kind": "implementation",
        "display_name": descriptor.get("display_name", plugin_name),
        "summary": descriptor.get("description", f"BenchWeave plugin {package_id}"),
        "released_at": released_at,
        "tags": [],
        "publisher_id": publisher,
        "maintainers": [
            {"name": publisher, "contact": f"https://github.com/{publisher}"}
        ],
        "support_url": f"https://github.com/{publisher}",
        "issues_url": f"https://github.com/{publisher}/issues",
        "licence": {"spdx_expression": licence_spdx, "file": "LICENSE"},
        "source": {"url": source_url, "revision": revision},
        "compatibility": {
            "otdp_versions": [descriptor.get("otdp_version", "0.1.0")],
            "adapter_api_versions": [str(adapter.get("api_version", "1.0"))],
            "stg_versions": ["1.5"],
            "runtimes": [
                {
                    "os": "any",
                    "architecture": "any",
                    "python_version": _requires_python(pyproject),
                }
            ],
            "host_provider_ids": [],
        },
        "device_targets": [
            {
                "manufacturer": identity.get("manufacturer", "unknown"),
                "model": identity.get("model", plugin_name),
                "aliases": [],
                "firmware": _firmware_block(identity),
                "transports": [descriptor.get("transport", {}).get("type", "unknown")],
                "profile_ids": [],
                "descriptor_ids": [descriptor.get("id", plugin_name)],
            }
        ],
        "provides": {
            "profile_ids": [],
            "descriptor_ids": [descriptor.get("id", plugin_name)],
        },
        "dependencies": deps,
        "permissions": list(adapter.get("permissions", [])),
        "payload": _payload_block(payload_zip, members),
        "evidence": [
            {
                "level": "simulated",
                "report_path": "evidence/protocol-evidence.md",
                "tested_at": released_at,
                "target": "protocol layer",
                "result": "passed",
                "limitations": [
                    "self-attested conformance evidence; integrity-pinned, "
                    "content-unverified (CR-51)"
                ],
            }
        ],
        "changelog_path": "CHANGELOG.md",
        "migration_notes_path": "MIGRATION.md",
        "limitations": ["scope as per the evidence report; no unclaimed capability"],
    }
    manifest_bytes = canonical_bytes(manifest)
    submission: dict[str, Any] = {
        "submission_version": SUBMISSION_VERSION,
        "package_id": package_id,
        "version": release_version,
        "registry_id": registry_id,
        "manifest_sha256": sha256_hex(manifest_bytes),
        "source_revision": revision,
        "components": list(REQUIRED_COMPONENTS),
        "capability_declaration": capability_declaration,
        "transport_triples": [dict(triple) for triple in transport_triples],
        "firmware_attestation": firmware_attestation,
        "closure": closure,
        "closure_digest": closure_digest,
        "namespace_lookalikes": lookalikes,
    }
    _gate_submission_complete(submission, {path for path, _data in members})
    return SubmissionArtifacts(
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        payload_bytes=payload_zip,
        submission=submission,
        submission_bytes=canonical_bytes(submission),
        lookalikes=lookalikes,
    )


def validate_submission_draft(submission: dict[str, Any], member_paths: set[str]) -> None:
    """The public entry to the built-set completeness check (A4's sixth arm)."""
    _gate_submission_complete(submission, member_paths)


def _gate_submission_complete(submission: dict[str, Any], member_paths: set[str]) -> None:
    """The built set carries every required component (CR-1's self-check).

    A4's sixth arm routes through here: a publish-record draft without the
    closure diff refuses with ``closure_diff_absent``.
    """
    present: dict[str, bool] = {
        "adapter-source": any(path.startswith("plugin/") for path in member_paths),
        "build-provenance": "build-provenance.json" in member_paths,
        "conformance-evidence": any(path.startswith("evidence/") for path in member_paths),
        "dependency-lock": "dependency-lock.json" in member_paths,
        "descriptor": any(path.startswith("descriptors/") for path in member_paths),
        "licence": "LICENSE" in member_paths,
        "payload-inventory": bool(submission.get("manifest_sha256")),
        "release-manifest": bool(submission.get("manifest_sha256")),
    }
    if submission.get("capability_declaration") is None:
        raise PublishingError(
            "capability_declaration_absent: the submission draft carries no "
            "capability declaration (CR-45)"
        )
    if submission.get("closure") is None:
        raise PublishingError(
            "closure_diff_absent: the publish-record draft carries no closure "
            "diff versus the prior release (CR-38)"
        )
    missing = sorted(name for name, ok in present.items() if not ok)
    if missing:
        raise PublishingError(
            f"component_absent:{','.join(missing)} (the built set is incomplete)"
        )


def _existing_package_owners(registry_clone: Path) -> dict[str, set[str]]:
    """Every published package id mapped to its recorded owners (publisher ids)."""
    owners: dict[str, set[str]] = {}
    releases = registry_clone / "releases"
    if not releases.is_dir():
        return owners
    for manifest_path in releases.rglob("manifest.json"):
        parts = manifest_path.relative_to(releases).parts
        if len(parts) != 5:
            continue
        manifest = json.loads(manifest_path.read_bytes())
        owners.setdefault(f"{parts[1]}/{parts[2]}", set()).add(
            str(manifest.get("publisher_id", parts[1]))
        )
    return owners


def _registry_id(registry_clone: Path) -> str:
    releases = registry_clone / "releases"
    if releases.is_dir():
        for child in sorted(releases.iterdir()):
            if child.is_dir():
                return child.name
    return "benchweave-registry"


def _pyproject_version(pyproject: Path) -> str | None:
    if not pyproject.is_file():
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else None


def _requires_python(pyproject: Path) -> str:
    if pyproject.is_file():
        match = re.search(
            r'requires-python\s*=\s*">=\s*([\d.]+)"', pyproject.read_text(encoding="utf-8")
        )
        if match:
            return match.group(1)
    return "3.13"


def _firmware_block(identity: dict[str, Any]) -> dict[str, Any]:
    policy = identity.get("firmware_policy")
    if policy in ("listed", "commissioning_required"):
        return {"policy": policy, "versions": []}
    return {"policy": "commissioning_required", "versions": []}


def validate_transport_triple(triple: str) -> dict[str, str]:
    """Parse ``<id>@<version>:<sha256>`` — the admitted contract triple shape."""
    match = re.fullmatch(r"([^@:]+)@([^@:]+):([a-f0-9]{64})", triple)
    if match is None:
        raise PublishingError(
            f"transport_triple_invalid:{triple!r} (expected <id>@<version>:<sha256>)"
        )
    return {"id": match.group(1), "version": match.group(2), "sha256": match.group(3)}


def parse_dependency(spec: str) -> dict[str, Any]:
    """Parse ``<registry_id>/<package_id>@<version>:<manifest_sha256>``."""
    match = re.fullmatch(
        r"([a-z0-9][a-z0-9-]*)/([a-z0-9][a-z0-9._/-]*)@((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)):([a-f0-9]{64})",
        spec,
    )
    if match is None:
        raise PublishingError(
            f"dependency_invalid:{spec!r} (expected <registry_id>/<package_id>@<version>:<sha256>)"
        )
    return {
        "registry_id": match.group(1),
        "package_id": match.group(2),
        "version": match.group(3),
        "manifest_sha256": match.group(4),
    }


def _safe_member_path(root: Path, name: str) -> Path:
    """Containment-checked relative path (the packaging.py inventory discipline)."""
    relative = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or relative.is_absolute()
        or any(part in (".", "..") for part in name.split("/"))
    ):
        raise PublishingError(f"unsafe artefact path: {name}")
    return root / relative


# --- the git-native submission channel (CR-6) ------------------------------------


def submission_branch(
    registry_clone: Path,
    artifacts_dir: Path,
    submission: dict[str, Any],
    *,
    base: str = "main",
) -> tuple[str, Path, str | None]:
    """Stage a packaged artefact set into a registry-repo working copy.

    Creates the submission branch off ``base``, copies the artefact set under
    ``records/submissions/<publisher>/<plugin>/<version>/artefacts/`` and
    commits it. No service is required at any point: the PR (when ``gh`` is
    present) is sugar on top of a branch plus a compare URL. Returns
    (branch name, staging dir, remote URL or None).
    """
    package_id = str(submission["package_id"])
    version = str(submission["version"])
    publisher, plugin = package_id.split("/", 1)
    branch = f"submission/{publisher}-{plugin}-{version}"
    target = (
        registry_clone
        / "records"
        / "submissions"
        / publisher
        / plugin
        / version
        / "artefacts"
    )
    if target.exists():
        raise PublishingError(
            f"submission_staged_already:{target} (a prior staging exists; "
            "remove it before re-submitting)"
        )
    _run_git(registry_clone, "checkout", "-b", branch, base)
    target.mkdir(parents=True)
    for name in ("manifest.json", "payload.zip", "submission.json"):
        source = artifacts_dir / name
        if not source.is_file():
            raise PublishingError(
                f"component_absent:release-manifest ({name} missing from {artifacts_dir})"
            )
        (target / name).write_bytes(source.read_bytes())
    _run_git(registry_clone, "add", str(target.relative_to(registry_clone)))
    _run_git(
        registry_clone,
        "commit",
        "-m",
        f"submission: {package_id}@{version} (benchweave-sdk submit)",
    )
    remote = _run_git(registry_clone, "remote", "get-url", "origin")
    return branch, target, remote.strip() or None


def _run_git(cwd: Path, *args: str) -> str:
    import subprocess  # noqa: PLC0415 — beside its only use

    completed = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise PublishingError(
            f"git_failed:{args[0]}: {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout
