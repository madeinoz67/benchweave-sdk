"""#556 Track B B3 first commit: the vendor-profile seam (design record
``.claude/deep-review/2026-10-25-issue556-track-b-vocabularies.md`` §0.2
and §9 risk 1 — the falsifier arm, run before any derivation code moves).

The seam the composed-member mechanism rides: a descriptor may claim a
profile id no served corpus row carries, because the canonical validator
builds its profile map from EVERY document in the set — served AND pinned
(#446 slice 2) — and the descriptor's ``profiles[]`` is namespace-open. A
composed-member declaration carrying the schema's ``profiles`` array (one
vendor row, the device-profile-catalog's own row shape under the plural
key the validator's map reads) therefore admits vendor targets under the
EXISTING rule, with no validator weakening and no plugin-ui schema change.

The arms drive the REAL pinned-document path (``merge_pinned_documents``)
and the REAL validator (``validate_presentation`` from the vendored
contracts twin) over the REAL served-document builder
(``presentation._pinned_schemas``), with the declaration validated
against the REAL vendored 0.5.0 schema first — a schema-valid declaration
is a readable one. The negative control derives the RED direction: the
same target over the un-merged served set reports ``capability_mismatch``,
so the seam is load-bearing, not decorative.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pytest import raises

from benchweave_sdk.presentation import _contract, _pinned_schemas, check_ui
from benchweave_sdk.served import active_version
from benchweave_sdk.validation import contract_documents, validate_descriptor

type JsonObject = dict[str, Any]

contract = _contract()

FIXTURES = Path(__file__).parent / "fixtures" / "classref"

#: Invented vendor identity throughout (CLAUDE.md §4): a Meridian M-400
#: shape on the Veridian f1 fixture body.
VENDOR_PROFILE_ID = "com.meridian.m400/1.0.0"
VENDOR_ACTION = "com.meridian.m400.calibrate/1.0.0"
VENDOR_SCHEMA_ID = "urn:meridian:action:calibrate:1.0.0:input"

MEMBER_DECLARATION_NAME = "member-declaration.json"
VENDOR_CATALOG_NAME = "meridian-catalog.json"


def _raw(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _vendor_input_schema() -> JsonObject:
    return {
        "type": "object",
        "properties": {
            "calibration_point": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 10.0,
            }
        },
        "required": ["calibration_point"],
        "additionalProperties": False,
        "$id": VENDOR_SCHEMA_ID,
    }


def _vendor_catalog() -> JsonObject:
    return {
        "catalog_version": "1.0.0",
        "vendor": "com.meridian",
        "actions": {
            VENDOR_ACTION: {
                "description": "Run the M-400 self-calibration.",
                "input_schema": _vendor_input_schema(),
                "output_schema": {"type": "object"},
                "side_effect": "state_change",
            }
        },
    }


def _vendor_profile_row(profile_id: str = VENDOR_PROFILE_ID) -> JsonObject:
    """The device-profile-catalog's own row shape, verbatim field set."""
    return {
        "id": profile_id,
        "title": "Meridian M-400 composed profile",
        "channel_roles": ["digital_input"],
        "required_actions": [VENDOR_ACTION],
        "optional_actions": [],
    }


def _member_declaration(
    profiles: list[JsonObject] | None = None,
) -> JsonObject:
    """A schema-valid composed-member declaration carrying the vendor
    profile row (the seam's payload) and one configuration member."""
    document: JsonObject = {
        "contract_version": "0.1.0",
        "profiles": profiles if profiles is not None else [_vendor_profile_row()],
        "members": [
            {
                "slot": "calibrate",
                "kind": "configuration",
                "claims": [VENDOR_ACTION],
                "schema_source": "input_schema",
                "page": "configuration",
            }
        ],
    }
    return document


def _seam_descriptor() -> JsonObject:
    """The f1 fixture body claiming the vendor profile and declaring the
    vendor action, with both pinned documents on the contracts seam."""
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    descriptor["profiles"].append(VENDOR_PROFILE_ID)
    descriptor["actions"][VENDOR_ACTION] = {
        "binding": {"kind": "adapter", "key": "fixture"},
        "input_constraints": {
            "properties": {"calibration_point": {"type": "number"}},
        },
        "timeout_ms": 30000,
        "side_effect": "state_change",
        "cancellable": True,
        "retry": "never",
    }
    for name, document in (
        (MEMBER_DECLARATION_NAME, _member_declaration()),
        (VENDOR_CATALOG_NAME, _vendor_catalog()),
    ):
        descriptor["contracts"].append(
            {
                "id": f"urn:meridian:{name.removesuffix('.json')}:1.0.0",
                "path": name,
                "sha256": _digest(_raw(document)),
            }
        )
    return descriptor


def _declaration_schema() -> JsonObject:
    key = (
        f"plugin-ui-class-reference/{active_version('plugin-ui-class-reference')}"
        "/composed-member-declaration.schema.json"
    )
    schema: JsonObject = contract_documents()[key]
    return schema


def _pinned_documents(
    scratch: Path, *, declaration: JsonObject | None = None
) -> dict[str, JsonObject]:
    """Write the pinned documents beside the descriptor (digests already
    computed by the descriptor builder) and return them for the merge."""
    documents: dict[str, JsonObject] = {}
    scratch.mkdir(parents=True, exist_ok=True)
    declaration = declaration if declaration is not None else _member_declaration()
    (scratch / MEMBER_DECLARATION_NAME).write_bytes(_raw(declaration))
    documents["member-declaration"] = declaration
    catalog = _vendor_catalog()
    (scratch / VENDOR_CATALOG_NAME).write_bytes(_raw(catalog))
    documents["meridian-catalog"] = catalog
    return documents


def _validate_declaration(document: JsonObject) -> None:
    """The declaration is schema-valid per the REAL vendored 0.5.0 schema
    (the family's own closed sets, not a test-side restatement)."""
    findings = sorted(
        Draft202012Validator(_declaration_schema()).iter_errors(document),
        key=lambda error: list(error.path),
    )
    assert not findings, f"declaration fails the vendored schema: {findings[0].message}"


def _vendor_target() -> JsonObject:
    return {
        "id": "calibrate",
        "kind": "configuration",
        "action_id": VENDOR_ACTION,
        "profile_ids": [VENDOR_PROFILE_ID],
        "input_schema_id": VENDOR_SCHEMA_ID,
        "schema_asset_id": "settings",
        "preset_asset_ids": [],
    }


def _validate_with(
    documents: JsonObject,
    *,
    descriptor: JsonObject,
    target: JsonObject,
) -> Any:
    """The real validator over a vendor configuration-target specimen.

    Mirrors the corpus specimen shape (``test_presentation_profiles``) with
    every version-bearing line derived from the served set, never hardcoded:
    the target under test names the VENDOR profile id, which no served
    corpus row carries.
    """
    descriptor_raw = _raw(descriptor)
    schema_raw = _raw(_vendor_input_schema())
    version = active_version("plugin-ui")
    manifest = {
        "contract_version": version,
        "plugin_id": descriptor["id"],
        "descriptor_sha256": _digest(descriptor_raw),
        "bindings": [
            {"id": "calibrate", "kind": "configuration", "target_id": "calibrate"}
        ],
        "pages": [
            {
                "id": "settings",
                "kind": "configuration",
                "title": "Settings",
                "bindings": ["calibrate"],
                "required": True,
            }
        ],
        "assets": [
            {"id": "settings", "path": "settings.json", "sha256": _digest(schema_raw)}
        ],
    }
    catalogue = {
        "contract_version": version,
        "descriptor_sha256": _digest(descriptor_raw),
        "targets": [target],
    }
    envelope = {
        "contract_version": version,
        "descriptor_sha256": _digest(descriptor_raw),
        "resource_root": "ui",
        "manifest": {"path": "manifest.json", "sha256": _digest(_raw(manifest))},
    }
    resources = {"settings.json": schema_raw, "manifest.json": _raw(manifest)}
    return contract.validate_presentation(
        _raw(envelope),
        descriptor_raw=descriptor_raw,
        resources=resources,
        binding_catalogue=catalogue,
        schema_documents=documents,
        supported_features=frozenset(),
        supported_panels=frozenset(),
        firmware="1.0",
    )


def test_the_vendored_schema_admits_the_seam_declaration() -> None:
    """The declaration carrying the vendor profile row (plural ``profiles``
    key, exactly one row) is valid against the vendored 0.5.0 schema — the
    spelling the validator's profile map reads, so a schema-valid
    declaration is a readable one."""
    _validate_declaration(_member_declaration())


def test_the_descriptor_claiming_a_vendor_profile_id_validates(tmp_path: Path) -> None:
    """Risk #1's admission half, falsified: the REAL descriptor checker
    admits a profile id that no served corpus row carries and that is not
    ``otdp.*``-namespaced — the descriptor's ``profiles[]`` is
    namespace-open and no semantic check refuses a non-corpus id."""
    descriptor = _seam_descriptor()
    validate_descriptor(descriptor)
    pinned = _pinned_documents(tmp_path / "seam")
    # The pins verify against the written bytes: the descriptor's own
    # digest seam is honest before the merge consumes the documents.
    for row in descriptor["contracts"]:
        if not str(row["id"]).startswith("urn:meridian:"):
            continue
        raw = (tmp_path / "seam" / str(row["path"])).read_bytes()
        assert _digest(raw) == row["sha256"], row["path"]
    assert set(pinned) == {"member-declaration", "meridian-catalog"}


def test_the_seam_admits_a_vendor_target_green(tmp_path: Path) -> None:
    """The seam arm proper (design §5, B3 first commit): the declaration's
    profile row merges through the REAL pinned-document path into the REAL
    served set, and the REAL validator resolves the vendor configuration
    target with zero findings — no ``capability_mismatch``, no
    ``unresolved_reference``, no ``profile_shadow``."""
    descriptor = _seam_descriptor()
    pinned = _pinned_documents(tmp_path / "seam")
    merged = contract.merge_pinned_documents(_pinned_schemas(descriptor), pinned)
    report = _validate_with(merged, descriptor=descriptor, target=_vendor_target())
    codes = [finding.code for finding in report.findings]
    assert report.valid, report.findings
    assert "capability_mismatch" not in codes
    assert "unresolved_reference" not in codes
    assert "profile_shadow" not in codes


def test_the_unmerged_served_set_refuses_the_vendor_target(tmp_path: Path) -> None:
    """The negative control (the RED direction): over the served set alone
    the same target reports ``capability_mismatch`` — the pinned profile
    row is what closes it, so the seam is load-bearing."""
    descriptor = _seam_descriptor()
    _pinned_documents(tmp_path / "seam")
    report = _validate_with(
        _pinned_schemas(descriptor), descriptor=descriptor, target=_vendor_target()
    )
    assert not report.valid
    assert contract.Finding(
        "capability_mismatch",
        "targets.calibrate",
        "Target exceeds descriptor capabilities",
    ) in report.findings


def test_a_declaration_redeclaring_a_corpus_id_divergently_shadows(tmp_path: Path) -> None:
    """The declaration does not launder profile rows: re-declaring a CORPUS
    profile id with a divergent row keeps the #446 ``profile_shadow``
    refusal on a target that binds the shadowed id."""
    corpus_profile_id = "otdp.logic_analyser/1.0.0"
    divergent = _vendor_profile_row(profile_id=corpus_profile_id)
    divergent["optional_actions"] = ["otdp.logic_analyser.decode/1.0.0"]
    declaration = _member_declaration(profiles=[divergent])
    _validate_declaration(declaration)
    descriptor = _seam_descriptor()
    descriptor["profiles"] = [corpus_profile_id]
    pinned = _pinned_documents(tmp_path / "shadow", declaration=declaration)
    merged = contract.merge_pinned_documents(_pinned_schemas(descriptor), pinned)
    target = {
        **_vendor_target(),
        "profile_ids": [corpus_profile_id],
    }
    report = _validate_with(merged, descriptor=descriptor, target=target)
    assert not report.valid
    assert contract.Finding(
        "profile_shadow",
        "targets.calibrate",
        f'Profile id "{corpus_profile_id}" is declared with divergent rows '
        "by multiple documents",
    ) in report.findings


# ---------------------------------------------------------------------------
# B4 motion 1 — the seam wired into the production call (#556 Track B record,
# B3 fold's recorded fact 1: ``validate_presentation`` still passed the
# served-only document map, so a vendor target failed the REAL ``check-ui``
# with ``capability_mismatch`` until the pinned-document merge rides that
# path). These arms drive ``check_ui`` — the shipped call the CLI's
# ``check-ui`` runs, loading every byte from disk — never the test-side
# manual merge above.
# ---------------------------------------------------------------------------


def _check_ui_package(
    scratch: Path,
    *,
    with_declaration_pin: bool = True,
    descriptor: JsonObject | None = None,
    extra_pins: dict[str, JsonObject] | None = None,
) -> Path:
    """A real presentation package on disk: envelope, descriptor with its
    digest-pinned plugin documents beside it, binding catalogue carrying the
    vendor configuration target, and the ui/ resource tree — the layout
    ``check_ui`` loads. ``descriptor`` substitutes a pre-built descriptor
    (every digest below is computed over the substituted bytes, so a variant
    package stays internally consistent); ``extra_pins`` writes additional
    pinned documents beside the package.
    """
    descriptor = descriptor if descriptor is not None else _seam_descriptor()
    if descriptor is not None and not with_declaration_pin:
        descriptor["contracts"] = [
            row
            for row in descriptor["contracts"]
            if row["path"] != MEMBER_DECLARATION_NAME
        ]
    schema_raw = _raw(_vendor_input_schema())
    version = active_version("plugin-ui")
    manifest = {
        "contract_version": version,
        "plugin_id": descriptor["id"],
        "descriptor_sha256": _digest(_raw(descriptor)),
        "bindings": [
            {"id": "calibrate", "kind": "configuration", "target_id": "calibrate"}
        ],
        "pages": [
            {
                "id": "settings",
                "kind": "configuration",
                "title": "Settings",
                "bindings": ["calibrate"],
                "required": True,
            }
        ],
        "assets": [
            {"id": "settings", "path": "settings.json", "sha256": _digest(schema_raw)}
        ],
    }
    catalogue = {
        "contract_version": version,
        "descriptor_sha256": _digest(_raw(descriptor)),
        "targets": [_vendor_target()],
    }
    envelope = {
        "contract_version": version,
        "descriptor_sha256": _digest(_raw(descriptor)),
        "resource_root": "ui",
        "manifest": {"path": "manifest.json", "sha256": _digest(_raw(manifest))},
    }
    package = scratch / "pkg"
    (package / "ui").mkdir(parents=True)
    (package / "descriptor.json").write_bytes(_raw(descriptor))
    (package / MEMBER_DECLARATION_NAME).write_bytes(_raw(_member_declaration()))
    (package / VENDOR_CATALOG_NAME).write_bytes(_raw(_vendor_catalog()))
    for name, document in (extra_pins or {}).items():
        (package / name).write_bytes(_raw(document))
    # The f1 fixture body's own pin: its file rides the package so the
    # descriptor-relative pin walk verifies every digest it names.
    (package / "vendor-catalog.json").write_bytes(
        (FIXTURES / "vendor-catalog.json").read_bytes()
    )
    (package / "presentation.json").write_bytes(_raw(envelope))
    (package / "binding-catalogue.json").write_bytes(_raw(catalogue))
    (package / "ui" / "manifest.json").write_bytes(_raw(manifest))
    (package / "ui" / "settings.json").write_bytes(schema_raw)
    return package


def test_the_real_check_ui_resolves_the_vendor_target(tmp_path: Path) -> None:
    """The production arm (#556 B4 motion 1): through the SHIPPED
    ``check_ui`` call — bytes loaded from disk, the served map built
    in-process — a vendor configuration target the declaration's profile
    row admits resolves with ZERO findings. The B3 arms above prove the
    validator, the vendored schema and the merge agree; this arm proves
    the route a plugin author actually runs carries them."""
    package = _check_ui_package(tmp_path)
    report = check_ui(
        package / "presentation.json",
        package / "descriptor.json",
        package,
        package / "binding-catalogue.json",
        firmware="1.0",
        features=frozenset(),
        panels=frozenset(),
    )
    assert report.valid, [(f.code, f.path, f.message) for f in report.findings]


def test_the_real_check_ui_without_the_pin_still_refuses(tmp_path: Path) -> None:
    """The production negative control: the same package with the
    member-declaration pin absent from the descriptor (the profile id
    stays claimed, the vendor catalog pin stays) reports
    ``capability_mismatch`` — the pinned profile row is what closes the
    target's admission, so the wiring is load-bearing, not decorative."""
    package = _check_ui_package(tmp_path, with_declaration_pin=False)
    report = check_ui(
        package / "presentation.json",
        package / "descriptor.json",
        package,
        package / "binding-catalogue.json",
        firmware="1.0",
        features=frozenset(),
        panels=frozenset(),
    )
    assert not report.valid
    assert contract.Finding(
        "capability_mismatch",
        "targets.calibrate",
        "Target exceeds descriptor capabilities",
    ) in report.findings


# ---------------------------------------------------------------------------
# #556 B4 fold F3 — derive and check-ui agree on colliding pinned $ids. The
# vendored merge guard refuses a pin whose embedded $id shadows a served $id
# or aliases a sibling pin's (#446 slice 2) — but only check-ui ran it, so
# two pinned catalogs sharing an input-schema $id derived GREEN (the walk
# keys actions by URN and never reads $ids) and the author learned at
# check-ui, packages already derived. The walk now runs the SAME vendored
# guard over the accepted pin set, under the guard's own code.
# ---------------------------------------------------------------------------


def _shared_id_catalogs() -> tuple[JsonObject, JsonObject]:
    """Two vendor catalogs whose actions share one input-schema $id."""
    shared = "urn:meridian:action:shared:1.0.0:input"

    def catalog(urn: str, field: str) -> JsonObject:
        return {
            "catalog_version": "1.0.0",
            "vendor": "com.meridian",
            "actions": {
                urn: {
                    "description": f"Vendor {field}.",
                    "input_schema": {
                        "type": "object",
                        "properties": {field: {"type": "number"}},
                        "required": [field],
                        "$id": shared,
                    },
                    "output_schema": {"type": "object"},
                    "side_effect": "state_change",
                }
            },
        }

    return (
        catalog("com.meridian.m400.capture/1.0.0", "shots"),
        catalog("com.meridian.m400.digitize/1.0.0", "frames"),
    )


def test_two_pins_sharing_an_input_schema_id_refuse_at_derive(
    tmp_path: Path,
) -> None:
    """The two halves agree: two pinned catalogs sharing an input-schema
    $id refuse the DERIVE under the vendored guard's own code — the same
    refusal check-ui's merge reports — never a green derivation that only
    the validator catches later."""
    from benchweave_sdk.classref import derive_ui, find_reference

    capture, digitize = _shared_id_catalogs()
    descriptor = json.loads((FIXTURES / "descriptor-f1.json").read_bytes())
    scratch = tmp_path / "shared-id"
    scratch.mkdir()
    for name, document in (
        ("meridian-capture.json", capture),
        ("meridian-digitize.json", digitize),
    ):
        (scratch / name).write_bytes(_raw(document))
        for urn in document["actions"]:
            descriptor["actions"][urn] = {
                "binding": {"kind": "adapter", "key": "fixture"},
                "input_constraints": {},
                "timeout_ms": 30000,
                "side_effect": "state_change",
                "cancellable": True,
                "retry": "never",
            }
        descriptor["contracts"].append(
            {
                "id": f"urn:meridian:{name.removesuffix('.json')}:1.0.0",
                "path": name,
                "sha256": _digest(_raw(document)),
            }
        )
    for pin in ("vendor-catalog.json", "vectors-f1.json"):
        (scratch / pin).write_bytes((FIXTURES / pin).read_bytes())
    (scratch / "descriptor.json").write_bytes(_raw(descriptor))
    with raises(ValueError, match="^pinned_id_shadow:") as raised:
        derive_ui(
            (scratch / "descriptor.json").read_bytes(),
            find_reference("otdp.logic_analyser/1.0.0"),
            descriptor_path=scratch / "descriptor.json",
        )
    assert "urn:meridian:action:shared:1.0.0:input" in str(raised.value)


def test_check_ui_reports_the_shared_id_as_the_same_code(tmp_path: Path) -> None:
    """The check-ui half, unchanged by the fold and asserted beside it: the
    same two pins through the SHIPPED check_ui call report the finding under
    the guard's code — derive and check-ui now refuse the same shape with
    the same name."""
    capture, digitize = _shared_id_catalogs()
    descriptor = _seam_descriptor()
    for name, document in (
        ("meridian-capture.json", capture),
        ("meridian-digitize.json", digitize),
    ):
        descriptor["contracts"].append(
            {
                "id": f"urn:meridian:{name.removesuffix('.json')}:1.0.0",
                "path": name,
                "sha256": _digest(_raw(document)),
            }
        )
    package = _check_ui_package(
        tmp_path / "shared-id-ui",
        descriptor=descriptor,
        extra_pins={
            "meridian-capture.json": capture,
            "meridian-digitize.json": digitize,
        },
    )
    report = check_ui(
        package / "presentation.json",
        package / "descriptor.json",
        package,
        package / "binding-catalogue.json",
        firmware="1.0",
        features=frozenset(),
        panels=frozenset(),
    )
    assert not report.valid
    assert [finding.code for finding in report.findings] == ["pinned_id_shadow"]


# ---------------------------------------------------------------------------
# #556 B4 fold F4 — an ignored pin contributes nothing anywhere. A
# digest-verified document matching none of the walk's pin shapes is
# disclosed as ignored ("contributed nothing") — yet its profile row still
# landed in the validator's admission map, so a target naming that profile
# validated: the disclosure's claim was false at check-ui. Only documents
# the walk accepts may reach the map; the declaration shape (``members``,
# with its optional profile row) is what carries a row.
# ---------------------------------------------------------------------------


def _profiles_only_package(tmp_path: Path) -> Path:
    """The check-ui package with the member-declaration pin replaced by a
    profiles-ONLY document — the same vendor row, no members, the shape the
    walk ignores and discloses every run."""
    profiles_only = {
        "contract_version": "0.1.0",
        "profiles": [_vendor_profile_row()],
    }
    descriptor = _seam_descriptor()
    for row in descriptor["contracts"]:
        if row["path"] == MEMBER_DECLARATION_NAME:
            row["path"] = "profiles-only.json"
            row["sha256"] = _digest(_raw(profiles_only))
    return _check_ui_package(
        tmp_path / "profiles-only",
        descriptor=descriptor,
        extra_pins={"profiles-only.json": profiles_only},
    )


def test_an_ignored_shape_pin_stops_admitting_the_target(tmp_path: Path) -> None:
    """The ignored-shape pin must stop admitting the target: the walk
    discloses it as having contributed nothing, and after the fold the
    validator's map agrees — the same package that admitted the vendor
    target now reports capability_mismatch, exactly as the negative control
    with no pin at all."""
    package = _profiles_only_package(tmp_path)
    report = check_ui(
        package / "presentation.json",
        package / "descriptor.json",
        package,
        package / "binding-catalogue.json",
        firmware="1.0",
        features=frozenset(),
        panels=frozenset(),
    )
    assert not report.valid
    assert contract.Finding(
        "capability_mismatch",
        "targets.calibrate",
        "Target exceeds descriptor capabilities",
    ) in report.findings


def test_the_walk_still_ignores_the_profiles_only_pin(tmp_path: Path) -> None:
    """The disclosure keeps its truth's other half: the same profiles-only
    document rides the DERIVE as an ignored pin — disclosed on every run,
    contributing nothing — so the fold made the disclosure true everywhere
    rather than silencing it."""
    from benchweave_sdk.classref import derive_ui, find_reference

    package = _profiles_only_package(tmp_path / "ignored-derive")
    derived = derive_ui(
        (package / "descriptor.json").read_bytes(),
        find_reference("otdp.logic_analyser/1.0.0"),
        descriptor_path=package / "descriptor.json",
    )
    assert "profiles-only.json" in derived.ignored_pins, derived.ignored_pins
