# Issue #147 — Transport providers: the reviewed host-provider contract mechanism

- Date: 2026-09-22
- Status: design (pre-implementation; this record precedes any corpus or SDK change on
  `feat/147-transport-providers`); refute fold 2026-09-22 — mechanism-critic F1–F11
  folded into this record and the corpus branch by owner directive; adversary lane
  pending, its findings fold as a late wave
- References: gateway issue [#147](https://github.com/madeinoz67/benchweave/issues/147)
  (carrier for deferral row 6 of the #43 design of record, re-keyed to transport by
  Amendment 3), gateway issues #43 and #95; SDK base `4ba28b9`
- Scope: the **mechanism** only — how a descriptor declares it needs a non-scoped
  transport, what the review/approval surface is, what the host grants. Provider
  implementations themselves are out of scope by the issue's own text.

## 0. Grounding — verified against code and corpus, not the issue prose

Every claim below was checked this session against the vendored 0.2.0 tree and the
canonical corpus/gateway source.

1. **The corpus already promises this lane and already contains its seam.**
   `otdp-specification.md` §8.1 (0.2.0, main-side
   `standards/otdp/0.2.0/otdp-specification.md`): "The initial generic HostServices has
   no `custom` transaction kind. **An integration declaring transport custom must
   reference a separately documented and admitted host-service extension.** An agent
   cannot mark it complete using these generic services alone. The core never falls
   back to unrestricted I/O." And §6.4: "`serial`, `i2c`, `spi` and `custom` require
   adapter mode… The adapter cannot turn a descriptor connection key into arbitrary
   host access." The increment does not open a new door; it builds the mechanism
   behind a sentence that currently has none.

2. **The descriptor seam exists: `$defs/customTransport`** (vendored
   `src/benchweave_sdk/standards/otdp/0.2.0/otdp-device-descriptor.schema.json`):
   `{type: "custom", connection_key: ^[a-z][a-z0-9_]*$, settings: {protocol_reference
   (required, free string), x-…}}`, description "connection_key resolves to a
   commissioned, scoped host transport. Addresses/paths/credentials are not granted by
   this descriptor." The transport `oneOf` has nine variants; the eight scoped ones
   plus `custom`.

3. **The pinning precedent exists: the root `contracts` array** —
   `{id, path, sha256}` items, package-relative path, sha256-pinned. The class examples
   pin the profile catalog and measurement schema this way (`examples/class-daq.json`:
   `urn:otdp:profile-catalog:0.2.0` + `dc776ec3…`). Contract references resolve
   relative to the host-admitted plugin bundle root, stay within it after symlink
   resolution, never identify a URL or executable module; external `$ref` retrieval is
   disabled (extension-contract §1).

4. **The feature-id precedent exists: `required_features`** — pattern
   `^[a-z][a-z0-9_.-]*/semver$`, must contain `otdp.core/0.1.0`; "every identifier must
   be understood by the host before admission… A well-formed unknown identifier is not
   automatically supported. Version matching is exact" (extension-contract §1). Known
   features today are the five lane ids plus the twelve catalog profile ids.

5. **The approval-document precedent exists: commissioning** —
   `standards/execution/0.1.0/commissioning.schema.json`: `{id, version, sha256}`
   document references throughout, `owners`, `approved_by/approved_at/expires_at`, and
   an `evidence[]` array of `{category, report{id,version,sha256}, tested_at, scope,
   result, limitations}` — with the description "Structure only. Apply … semantic and
   qualification rules; JSON validity grants no authority."

6. **The grant surface exists: `transfer`** — HostServices (spec §8) carries
   `transfer(transaction, context)` / `close_transport`, and §8.1 defines the closed
   transaction grammar (`stream_send/receive/exchange`, `can_receive/send`,
   `i2c_transfer`, `spi_transfer`) with "All transaction objects reject unspecified
   fields… transaction objects contain no host/path/credential fields." `transfer`
   already verifies context and records transmission evidence. The SDK's `MockHost`
   (`src/benchweave_sdk/testing.py`) scripts transfers as exact-dict matches — it is
   grammar-agnostic by construction.

7. **The permission already exists: `scoped_transport`** — closed enum
   (`scoped_transport`, `artifact_writer`, `event_sink`, `artifact_reader`) in
   `$defs/adapter.permissions`. S15 already ties capabilities to permissions.

8. **Plugin code cannot bring a vendor SDK, structurally.** The gateway's verified
   bundle loader (`src/benchweave/registry/otdp_loading.py`) admits imports of stdlib
   only — `admitted_import` raises `ImportError` for any non-stdlib top level, and
   native extensions are not supported. A "vendor SDK" therefore cannot be plugin
   payload; it can only be host-side behind a reviewed contract. This is why §6 frames
   the lane as *host-provider*.

9. **The gateway enforces none of the descriptor-admission surface at runtime today.**
   Verified by `git grep` over gateway `src/`: zero occurrences of `required_features`
   and zero of `connection_key`. The bridge (`host/otdp_bridge.py`) receives the
   descriptor dict from the caller; `host/services.py`'s HostServices protocol has no
   transport members. The #43 external review found the same for permissions ("Nothing
   in the gateway reads `integration.adapter.permissions`"). The corpus is explicitly
   "a design contract, not a claim that an STG SDK or plugin loader already exists"
   (spec §1) — the loader catches up in increments. A design that assumes live
   enforcement today is wrong; a design that refuses to move corpus-first is equally
   wrong, because the corpus is what both catch-up increments encode from.

10. **`x-` keys cannot carry this.** §3: "Optional namespaced `x-vendor-name` fields
    may be ignored at schema extension points; **required semantics MUST NOT depend on
    them**" (S18 bars safety-critical ignored extensions). A transport-provider
    dependency is admission-deciding semantics — the declaration must be a normative
    field, i.e. a corpus revision. (Contrast: Amendment 3's `x-capture-formats` site is
    legitimate precisely because standalone-capture formats are authoring-time
    metadata, not admission inputs.)

11. **Governance state.** OTDP is at 0.2.0, released 2026-09-19, supersedes 0.1.2;
    the 48-hour bump window (GOVERNANCE, #97) is clear. Change classes: additive
    machine errata (backwards-compatible) → PATCH, precedent "the interface
    `approver_token` pattern: new optional field, nothing removed or retyped"; breaking
    machine change → MINOR at least. Bump mechanics are copy-never-move + repin +
    export + report regen via the family writer. The SDK vendors machine artifacts
    only; prose companions are not digest-pinned.

12. **Trigger and lineage.** Three real integrations already meet deferral row 6's
    trigger (a real logic analyser, a real USB power meter, the webcam integration
    tracked at gateway issue #95). The merged design of record (main-side
    `.claude/deep-review/2026-09-21-issue43-capture-streaming-design.md`, current
    through Amendment 3, PR #145, merge `3160ec3`) states row 6 verbatim:

    > | 6 | Transport providers (UVC, vendor SDKs) | Documentation here | A device class
    > in scope whose transport is not one of the scoped primitives |

    and §11's disposition row: "**Defer** (row 6): separately reviewed host-provider
    contracts (extension-contract §6 says so verbatim)." The re-key is Amendment 3's,
    from the external review's second ask: the row was originally keyed to device
    class ("UVC, vendor SDKs"), but extension-contract §6 names USB-HID verbatim and
    *transport* is the right key — re-keying "would let the next plugin author see
    where they stand." The owner actioned it: row 6 re-keyed to transport with this
    issue as carrier. Neighbour rows that may interact: row 10 (external-tool capture
    adopt/ingest — sigrok-cli/ffmpeg-shaped workflows) and row 11 (thread-level
    watchdog for non-yielding adapter cleanup). Neither shares a surface with this
    design's corpus increment; row 10's adopted-capture workflows are a likely *user*
    of provider transports (a standalone capture tool speaking a provider grammar),
    not a collision — noted, not actioned here.

13. **Slice 1 of the #43 record is in flight (gateway issue #155, started this
    session).** Its own pins make the corpus surfaces disjoint by construction: "No
    standards bytes move in either repo; `sync-standards --check` stays green." Its
    gateway leg includes "Permission gating at registry admission — new read of
    `integration.adapter.permissions` (nothing reads it today)" — the one real
    adjacency with this design's increment 3 (see §3.1). Its SDK leg is one new
    additive module (standalone capture services) whose own text says "device I/O
    composed from a transport by the runner" — the composition seam §1.5 types. Its
    unchanged pins are `tests/contract/test_host_abi.py`, `tests/sdk/
    test_adapter_agreement.py`, `tests/integration/test_otdp_loading.py`; this design
    moves none of them (adapter ABI stays 1.1, so the adapter-agreement pin is
    untouched by construction).

## 1. Mechanism

Three parts, each extending a proven in-tree mechanism rather than inventing one.

### 1.1 Declaration — `transport.custom` gains a pinned `provider` object

The descriptor keeps `transport.type: "custom"` — that variant was built for exactly
this case — and gains one optional, self-contained object:

```json
"transport": {
  "type": "custom",
  "connection_key": "power_meter",
  "settings": {"protocol_reference": "vendor communications manual rev C"},
  "provider": {
    "feature_id": "otdp.transport.usb_hid/1.0.0",
    "id": "urn:otdp:transport-provider:usb-hid:1.0.0",
    "path": "transport-provider-usb-hid.json",
    "sha256": "<64 hex>"
  }
}
```

- `feature_id` follows the existing `required_features` pattern and **must** also
  appear in `required_features` (a semantic check in the S04 home; see 1.4).
- `{id, path, sha256}` is the root `contracts` item shape verbatim — package-relative
  path, digest-pinned, resolved inside the admitted bundle. The provider contract
  document ships in the plugin package and is pinned by the descriptor, exactly as the
  profile catalog is: the pin makes "the bytes that were reviewed" deterministic.
- When `provider` is absent, `custom` behaves exactly as today: the integration is
  honestly incomplete ("The relevant class may be fully specified while a particular
  device's transport integration remains unsupported" — extension-contract §6).

Why not a new `provider` transport variant in the `oneOf`: it would fork two shapes
that mean the same thing, and `custom` + `protocol_reference` is already the declared
home of "separately documented" transports. Why not ride the root `contracts` array
alone: the array is an unordered pin set; admission needs to know *which* pinned
contract is the transport provider without guessing URN conventions. One field, one
meaning.

### 1.2 Review/approval surface — a corpus-owned structure schema, host-admitted instances

A **transport-provider contract** is a JSON document validated by a new corpus machine
artifact, `otdp-transport-provider.schema.json` (Draft 2020-12, added to the otdp
normative set at 0.2.1). Structure only — the commissioning posture, "JSON validity
grants no authority":

- `contract_version` (const `0.1.0`), `id` (urn), `feature_id` (the id the host
  registers on admission), `version` (semver), `description`
- `transport_kind` (open string — `usb_hid`, `vendor_sdk`, …; each provider is its own
  contract, the corpus does not enumerate providers)
- `transaction_grammar[]`: `{kind (unique snake_case), request_schema, result_schema,
  limits}` — Draft 2020-12 subschemas, meta-validated, extending the §8.1 transfer
  grammar **for this provider only**. The host validates provider transactions against
  the admitted contract's grammar, never against the generic table.
- `security_scope`: closed enum of what the provider surface may touch —
  `commissioned_connection` only, in this revision. Filesystem paths, process
  spawning, and unrestricted network endpoints are unrepresentable **in
  `security_scope`** (adversary M1 — the wider "unrepresentable in the schema"
  claim was falsified live: hostile native_libraries/privileges and a
  credential-requiring grammar validate clean against the schema; the guard claims
  the class it catches and nothing wider). The other fields can still *describe*
  such things — review-read, never granted — so §6's no-direct-access property is
  machine-checkable exactly at the security_scope boundary and nowhere else.
- `host_requirements`: reviewed statement of what the host-side implementation needs
  (native library names + exact versions, privilege claims). This is where a vendor SDK
  lives: **host-side, named and reviewed — the plugin never imports it** (grounding 8).
- `approval`: `{approved_by, approved_at, expires_at}` + `evidence[]` in the
  commissioning evidence shape.

**Two review tiers, both named.** The *mechanism* (schema + rules) is corpus content
and rides the GOVERNANCE review path — standards-governor review, drift gates, family
suites, report regen. Each *provider contract instance* is admitted by the host
operator as a commissioning-class act: the document's own approval block plus the
host-side admission record. A descriptor pinning a provider contract that the host has
not admitted is an admission failure ("unknown required features fail admission" —
S04); device-supplied metadata still "cannot… add a new transport provider on its own"
(extension-contract §2). The pin gives determinism; the operator's admission gives
authority.

### 1.3 The grant — provider-scoped `transfer` kinds on the commissioned connection

The host hands the adapter **nothing structurally new**. `connection_key` continues to
resolve through commissioned gateway configuration to one scoped connection; for a
provider integration that connection is backed by the admitted provider's host-side
implementation. The adapter calls the existing `HostServices.transfer` with the
provider's transaction kinds (e.g. `{kind: "hid_transfer", report_id: …, data: …}`),
validated against the admitted contract's grammar.

Why transfer-grammar kinds and not new HostServices methods:

- `transfer` already enforces dispatch markers, deadlines, cancellation, byte bounds
  and transmission evidence — every provider gets that enforcement for free.
- The adapter ABI stays at 1.1 (`corpus-manifest.json` `identity.adapter_api`
  unchanged; no agreement-test churn).
- The SDK's `MockHost` scripts arbitrary transaction dicts by exact match — provider
  adapters are offline-testable with **zero** SDK testing-lane changes.
- The grammar table is already the corpus's per-transport shape catalog; a provider
  contract is one more, locally-admitted row-set. This is the literal reading of §8.1's
  "separately documented and admitted host-service extension."

`scoped_transport` remains the governing permission (S15) — a provider transfer *is* a
scoped transport. No new permission name.

### 1.4 The rules (corpus text) — where each check lives

| Rule | Home | Offline prefix (SDK lane) |
|---|---|---|
| `provider.feature_id` ∈ `required_features` | S04 (extended) | `provider_feature_missing:` |
| an `otdp.transport.*` id in `required_features` with no matching `transport.provider` | S04 (extended, orphan sweep) | `provider_transport_undeclared:` |
| any `otdp.*` id in `required_features` that is neither corpus-known (lanes, catalog profiles) nor declared via a `transport.provider` — the namespace is corpus-owned and closed offline (critic F2; typo'd `otdp.transports.*` must not sail through SDK-green) | S04 (extended, namespace closure) | `unknown_otdp_feature:` |
| a provider **contract's** own `feature_id` must live under `otdp.transport.*` — pattern-enforced on the provider schema + suite; the loading loop's known-features union must never mint other `otdp.*` ids, including fake core-feature versions (adversary M2 — executed: `otdp.core/9.9.9` was suite-green; contract-side twin of F2) | provider schema + admission | `provider_contract_invalid:` |
| pinned provider document exists at the descriptor-relative path and hashes to `sha256` (F5: the provider triple resolves **descriptor-relative** — §1's bundle-root rule governs the root `contracts` array; owner decision 2026-09-22, matching the built suite, Inc-2 text, and corpus example) | S14-family (package-relative paths) | `provider_contract_missing:` / `provider_contract_hash_mismatch:` |
| provider document passes `otdp-transport-provider.schema.json`; its grammar subschemas (`request_schema`/`result_schema`) meta-validate as Draft 2020-12 (F1 — the schema's `{"type":"object"}` holders admit invalid schemas otherwise; verified live); grammar `kind`s are unique as strings, not entries (F4 — `uniqueItems` catches exact dups only; verified live); and the three identity equalities hold — urn-embedded version == `version`, feature_id-embedded version == `version`, feature_id name segment == urn name segment (F3) | admission (new) + SDK `validate_transport_provider` | `provider_contract_invalid:` |
| `connection_key` resolves to a connection backed by the **same** admitted contract (exact id+version+sha256) | S12 (extended) | gateway-side (needs commissioned state — honestly not offline-checkable; disclosed) |
| provider transactions match the admitted grammar; `security_scope` respected | runtime | gateway-side |
| a provider grammar's kinds are disjoint from the seven generic §8.1 transfer kinds — "extends" is additive, never an override (corpus transport-providers §3 names the rule and the seven verbatim; the SDK's hand-carried frozenset is pinned by a spelling test with the spec cite — review finding 1) | provider validation (SDK + admission) | `provider_contract_invalid:` |
| gateway admission validates provider-contract instances against the vendored `otdp-transport-provider.schema.json` — `security_scope` is a boundary only once this exists (F8) | admission (Inc 3) | gateway-side |

The last three rows are the honest boundary of offline checking: the SDK proves the
declaration is *well-formed and self-consistent*; only the gateway can prove the
*grant* — because commissioned state and the provider runtime live there.

### 1.5 Standalone composition — the Decision 9 interplay

The #43 record's Decision 9 (standalone capture, Amendment 2) claims "one shape, two
backends" — an adapter running unchanged against the gateway's capture services or
the SDK's standalone filesystem writer. Amendment 3 scoped that claim to the capture
path, because for any adapter that talks to hardware it is not true as stated: nobody
supplies device I/O standalone while transport providers are deferred (external-review
finding 2 — the protocol is eight members including transport, and Decision 9
specified only a file writer). The evidence of what plugin authors do in the lane's
absence already exists: a contributor fork hand-rolled a serial host-services object
implementing all eight members, about a hundred lines, to make one adapter run
standalone at all.

This mechanism is what makes that composition standard instead of hand-rolled, on both
backends. The provider contract's `transaction_grammar` is the shared artifact: the
gateway validates provider transfers against the admitted contract; the #155
standalone leg composes "device I/O … from a transport by the runner"; and a
standalone provider backend implements the same grammar the MockHost already scripts.
One shape, three backends — gateway provider runtime, standalone provider backend,
MockHost — with the grammar, not any implementation, as the contract.

Where standalone provider backends live: author-side or harness-side, **not
SDK-shipped**. The SDK's wheel is self-contained and must not grow native HID/USB
dependencies (PKG-1/PKG-2); what the SDK ships is the schema validation and the
grammar-agnostic MockHost. A reference standalone provider backend (the documented
successor to that hand-rolled hundred lines) is deferral row 7.

## 2. Versioning — recommendation: OTDP 0.2.1 (PATCH)

The machine delta is additive by GOVERNANCE's own shape test: one optional object on
`$defs/customTransport`, one new schema file in the normative set, new examples;
nothing removed, nothing retyped, no existing document changes meaning: a descriptor
declaring 0.2.0 keeps validating under its own pinned version, unchanged (critic F9
reword — "validates identically under 0.2.1" overclaimed; a 0.2.0-declaring document
fails the 0.2.1 const by construction); provider descriptors are new documents that
old hosts refuse — which is the designed exact-matching posture, not a break. That is the
`approver_token` class → PATCH. It also matches the minimal-bumps directive (#69, and
the owner's stated baby-steps preference). The 48-hour window is clear (0.2.0 released
2026-09-19).

The counter-argument is semantic: a new admission lane is more than "errata". If the
standards-governor reads the PATCH row narrowly (corrections only), 0.3.0 is the
honest label — content identical, version re-keyed, one extra repin cycle. **Owner
fork F1**; recommendation 0.2.1. Either way the provider-contract instances themselves
are *not* governed standards — they are admitted local documents, "deliberately
versioned elsewhere" (GOVERNANCE) like profile ids and plugin releases. Their schema
living in the corpus is what keeps the corpus the single authority on descriptor
semantics.

## 3. Minimal first increment — repo split, sequencing, branches

Branch `feat/147-transport-providers` on both sides (per the issue). Four PRs, three
increments:

**Increment 1 — corpus (main-side PR A, first).** OTDP 0.2.1 by copy-never-move from
0.2.0: flip `otdp_version` const + `$id` + example version pins in the copy; add the
`provider` object to `$defs/customTransport`; add `otdp-transport-provider.schema.json`
to the normative set; add two synthetic examples (`examples/reference-provider.json` —
an invented USB-HID-class provider contract in the reference-* tradition — and a
reference descriptor declaring it); prose: extension-contract §6 expands the deferral
into the mechanism, spec §6.4/§8.1 gain the provider paragraphs, new companion
`transport-providers.md` (authoring + review obligations). Repin via the family
tooling, regenerate the devices validation report, export the bundle, move
manifests/identity/docs rows in-arc. Acceptance = the GOVERNANCE gates (drift,
coverage, family suites, `make check-sdk-standards`, `matrix --check`) green on the
merged result.

**Build-time amendment (2026-09-22, from the Increment-1 build):** the gates make
"green on the merged result" unreachable for a corpus-only PR A. `make
check-sdk-standards` exits 2 with exactly 56 failures (sdk_version_mismatch +
missing_asset + stale_generated + compatibility_incomplete) and 366 main-side tests
fail, all root-caused to the SDK lock/tree and the in-tree plugin descriptors still
sitting at 0.2.0 — none healable inside a standards-only scope guard. The 0.2.0 bump's
own commit disclosed the identical window (then 54 failures), so this is the bump
mechanic, not a defect. Landing order therefore follows the #80/#27 precedent:
Increment 2's SDK PR merges FIRST, then PR A opens carrying the corpus + the submodule
pointer (+ the equivalence extension, folding PR B — the module compares SDK and
corpus at the same version, so it belongs in the same merge). Four PRs becomes three:
SDK PR → main PR A (corpus + pointer + equivalence) → main PR C (admission seam).

**Increment 2 — SDK sync + offline conformance (this repo; unblocked by 1 alone).**
`sync-standards` to 0.2.1 (lock + vendored tree move version-first; STD-2 guards it);
`validate_descriptor` gains the S04 provider-consistency checks (1.4's rows,
including the F2 namespace closure); the `check` lane resolves and verifies the
pinned provider document descriptor-relative (F5); new `validate_transport_provider`
against the vendored schema — carrying F1's grammar-subschema meta-validation, F3's
three identity equalities, and F4's kind-string uniqueness; the six refusal
prefixes of 1.4 added to the STD-4 API list; fixture-lattice tests (§4); a short
user-guide subsection (obligation 1 — `check` gains CLI-visible refusals; the README
five-steps do not change). **No scaffold change** — the scaffolded descriptor uses the
serial transport and no provider; the CI scaffold-and-check run keeps proving the
golden shape. Lands here first, pushed; then **main-side PR B**: submodule pointer +
`tests/sdk/test_descriptor_equivalence.py` extended to run the SDK checker over the
0.2.1 example set and the shared provider lattice (the agreement property lives
main-side because only the parent sees both sides).

**Increment 3 — gateway admission/grant (main-side PR C).** The admission seam: the
known-features set grows by admitting provider contracts; descriptor admission
enforces the 1.4 table's gateway-side rows; permission-gate construction begins (the
#43 review already flagged it as unbuilt); the provider registry resolves
`connection_key` to provider-backed connections. Runtime provider implementations stay
out (the issue's own scope line).

The issue's stated order is corpus → gateway → SDK; this plan runs SDK second because
it is the cheapest falsification of the corpus shape — the offline lattice exercises
the 0.2.1 schema before the gateway bakes it in. **Owner fork F3** (sequencing);
recommendation as stated, increment 3 unchanged either way.

### 3.1 Disjointness and adjacency with capture slice 1 (#155, in flight)

Slice 1 of the #43 record started under gateway issue #155 — staged-append writer,
`dispatch(capture)`, capture-aware failure classification, and an SDK standalone-leg.
Its own pins and this design's shape give the surface map:

- **Corpus surface — disjoint by construction.** #155 moves no standards bytes in
  either repo (its own constraint); increment 1 is the only standards-bytes mover on
  this train. No bump-window interaction (only one OTDP bump exists).
- **SDK surface — different files, same repo main.** #155's SDK leg adds one new
  module (standalone capture services); this design's SDK leg touches the vendored
  tree + lock + `validation.py`/`conformance.py`/`cli.py` + tests. No shared file, but
  per the #69 discipline same-repo PRs serialize: #155's SDK leg is already in flight,
  so this design's SDK branch **rebases on it**, and each side runs a merge-result
  pre-check before push. Concretely: do not assume today's SDK `main` — it moves
  under this design.
- **Gateway admission — the one real adjacency; sequence, do not parallel.** #155
  lands "permission gating at registry admission — a new read of
  `integration.adapter.permissions`" in the same region this design's increment 3
  adds transport/provider validation. **Recommendation: increment 3 rebases on
  #155's admission read** — their slice is in flight, and their permissions wiring is
  machinery this design's provider-permission model builds on (`scoped_transport`
  rides the same read). Landing ours first would force a gratuitous rebase of an
  in-flight branch and duplicate the admission seam.
- **Pins — none moved.** #155 pins `tests/contract/test_host_abi.py`,
  `tests/sdk/test_adapter_agreement.py`, `tests/integration/test_otdp_loading.py`
  unchanged; this design's ABI stays at 1.1 so the adapter-agreement pin is untouched
  by construction, and the equivalence extension is confined to
  `tests/sdk/test_descriptor_equivalence.py` — not a #155 pin. If implementation
  discovers a need to move any pinned file, that is a collision to name loudly on both
  issues, not a silent pin-break.

## 4. Measurable proof — pre-committed acceptance rule

Written before any fixture was built or any number looked at.

**Metric 1 — lattice agreement (the drift proof).** A fixture lattice of **12**
provider descriptors: 4 valid variants (minimal provider declaration; provider + class
profile features together; provider with x- settings extensions; the corpus reference
descriptor itself) and 8 single-fault permutations (feature_id absent from
required_features; orphan `otdp.transport.*` feature; **unknown `otdp.*` feature id —
the namespace-closure fault, 1.4 row 3's lattice slot**; provider on a non-custom
transport; provider without adapter mode; pinned path escaping the package; **a
well-formed WRONG sha256** (a pattern-malformed digest is schema surface, refused
before hashing — proven by an extra arm); provider object with additional properties).
*Amended 2026-09-22 at Increment-2 review: the original list's settings-additionalProperties
slot was replaced by the closure fault — the shipped 0.2.1 schema catches that fault (and
two others of the eight) at the schema surface, which is the honest mapping; five of eight
prove the new prefixes, three prove the schema.* Requirement: the SDK lane (validate + check, run from the descriptor's
package root) and the corpus-0.2.1 rules applied through the main-side equivalence
module **agree accept/refuse on 12/12**, and each invalid fixture refuses with its
named prefix from 1.4.
- **Ship:** 12/12 with correct prefixes.
- **Kill:** any disagreement, or any missing/wrong prefix — the increment does not
  ship as-is; either the check or the corpus text is wrong, fix before merge. This is
  a population, not a sample: the 8 are the enumerated single-fault permutations of the
  declared fields; multi-fault compositions are excluded by design (residual, tracked
  as deferral 6).

**Metric 2 — RED control (the mechanism proof).** On the SDK branch, neutralize **only**
the provider-check mechanisms (API-preserving no-op bodies; a raw file revert makes the
lattice uncollectable because the test module imports the new API — the re-instrument
clause below covers exactly this): the 8 invalid fixtures must stop refusing with the named
prefixes (pass, or fail differently), the 4 valid ones still pass; restore, green
again. Paste both runs (raw pytest output, collected counts — `no tests ran` is a
FAILED check).
- **Ship:** refusals vanish on revert and return on restore.
- **Kill:** refusals surviving the revert mean the measurement tests the wrong layer —
  the run is **underpowered/mis-instrumented, not conclusive**; re-instrument before
  any conclusion. No ship on a failed RED.

**Metric 3 — goldens.** Post-sync: `sync-standards --check` green in all three lanes
(committed state, bundle mode, hatch build — STD-3 symmetry); scaffold output
**shape-identical** to the pre-change golden (SRF-1; amended 2026-09-22: literal
byte-identity is unsatisfiable across an OTDP const bump — the measured delta is the
version cites only, the descriptor's `otdp_version` value and the AI-GUIDE corpus cite
riding the train); lock records every 0.2.1 file, stamps
intact.
- **Ship:** all three green. **Kill:** any lane asymmetry or scaffold drift.

**Underpowered signal, pre-committed:** if Metrics 1–3 pass first-try with zero fixes
anywhere in the arc, treat the lattice as too weak (a mechanism this shape should
catch at least the hash and orphan cases distinctly) — add the multi-fault composition
fixtures before shipping. **F1 relabel:** a governor ruling of 0.3.0 re-keys the
version, it does not kill the increment.

## 5. Invariant impacts

- **STD-1/2/3** — content moves version-first (0.2.1) through the bundle; lock ↔ tree
  ↔ stamps symmetric across the three check lanes; no hand edits anywhere.
- **STD-4** — six new refusal prefixes join the machine-matchable API:
  `provider_feature_missing`, `provider_transport_undeclared`,
  `unknown_otdp_feature`, `provider_contract_missing`,
  `provider_contract_hash_mismatch`, `provider_contract_invalid` (critic F2 adds the
  namespace-closure prefix; invariants.md's list gains them; ordinary schema-shape
  failures keep flowing through the existing descriptor-validation error surface).
- **STD-5/TWO-1** — no normative byte moves SDK-side first; corpus lands main-side,
  is exported, arrives via sync; this repo's commit is pushed before the pointer.
- **PKG-1/2** — offline checks read the vendored tree and the plugin's own package
  files only; the provider document is hashed from disk, never fetched; wheel/sdist
  contents unchanged in shape (one more vendored JSON through the existing hook).
- **SRF-1** — no scaffold output change (verified: `scaffold.py`'s descriptor example
  is serial, provider-less; golden run is Metric 3).
- **SRF-2** — no plugin-ui surface touched; preview unaffected (transport is not a UI
  surface) — stated explicitly so no reviewer hunts for one.
- **SRF-3** — the new checks were written against the vendored 0.2.0 text this session
  and must be re-compared against the 0.2.1 bytes after sync, not memory.
- **CI cost** — no new job. Main-side: standards family suites + report regen +
  equivalence-extension runs (the corpus bump's standard cost). SDK-side: one more test
  module in the existing suite.

## 6. Deferrals — each with home and reopen trigger

| # | Deferred | Home | Reopen trigger |
|---|---|---|---|
| 1 | Gateway runtime grant wiring (provider registry, connection resolution, permission-gate construction) | New gateway issue at PR A merge (implementation lane of #147) | Corpus 0.2.1 merged; increment 3 starts |
| 2 | Provider implementations (USB-HID host provider, vendor-SDK bindings, the webcam integration) | Per-device gateway issues | First real device commissioned through the lane |
| 3 | Execution-side commissioning shape for provider-backed connections (the operator document admitting a provider instance bench-side) | Execution-standard queue | First provider implementation — it needs the operator admission surface |
| 4 | Registry exposure (published plugins declaring provider dependencies) | Registry-standard queue | First shared/published provider-dependent plugin |
| 5 | Typed SDK helpers for provider transaction kinds beyond generic `transfer` scripting | Gateway tracker (single stream) | A second provider contract lands and MockHost scripting proves repetitive |
| 6 | Multi-fault fixture compositions + provider-grammar fuzzing | Follow-on to increment 2 | The §4 underpowered signal fires (all green, zero fixes) |
| 7 | Reference standalone provider backend (the documented successor to a contributor's hand-rolled eight-member serial host services; author/harness-side — SDK-shipped backends rejected on PKG-1/2 grounds, the SDK ships schema validation + MockHost only) | Gateway tracker (single stream), documentation in the provider companion prose | First provider-backed adapter needing standalone runs (the Decision 9 composition demand, §1.5) |
| 8 | Suite self-arms for the uncanaried provider rules (measured 2026-09-22: pin-containment, pin-digest, subschema meta-validation, and the generic-disjoint file arm have NO in-suite self-arms — their only red controls are external ablations; and the subschema refusal is a crash that destroys the run summary rather than a named failure — fail-closed but coarse) | Gateway tracker (single stream); the ablation matrix is the interim control | The suite is relied on as its own gut-detector, or the next corpus bump touches the provider rules |
| 9 | Residual hardcoded current-corpus cites not moved in-arc with the bump (governor LOW-1: scripts/assemble_docs_site.py:437 stages/verifies superseded 0.2.0 bytes for the docs site; tests/contract/test_host_abi.py:4, tests/unit/test_derivation.py:3, tests/unit/test_presentation_specimens.py:34, src/benchweave/host/types.py:4, src/benchweave/measurement/derivation.py:19 — the #102 D2 stale-silent pattern). Zero coverage loss THIS bump (proven by the governor's version-stripped diff: runtime, measurement, and vectors differ only in version strings) | Documentation row (owner ruling 2026-09-22: the one follow-on-issue slot stays with deferral 1's gateway grant wiring, which has a scheduled carrier; this has none — generalization of #102 D2 manifest-discovery is the fix shape when it opens) | The next semantic OTDP bump, or any docs-site build that must stage 0.2.1 bytes |

## 7. Top risks — each with its falsifier

1. **The corpus runs ahead of a runtime that enforces none of it** (grounding 9). The
   SDK would check offline what nothing enforces online — the exact drift the promise
   guards against, deferred rather than solved. *Falsifier:* increment 3 landing
   without needing to reshape the provider object would validate the corpus; any
   reshape means 0.2.1's shape was wrong and a 0.2.2+ correction train is owed. The
   disclosure is the mitigation: the spec itself says the corpus is a design contract,
   and the issue chose corpus-first.
2. **Grant shape strains under a real provider.** If the first real integration (the
   webcam's capture-shaped traffic is the likely stress case) needs semantics
   `transfer` cannot express — device enumeration events, buffer streaming — the
   grammar-extension choice shows cracks; a standalone backend composes the same
   grammar, so it strains identically (§1.5). *Falsifier:* the first provider
   implementation needing a non-transfer call shape; then a services-surface row
   (new HostServices methods, adapter_api bump) opens as a design row, not a patch.
3. **Provider instances blur into corpus governance.** The design keeps provider
   contracts host-admitted, deliberately versioned elsewhere. If a second device
   family wants to *share* one contract, pressure pushes it toward the corpus tree and
   the two-tier split fails. *Falsifier:* reuse pressure at the second provider; then
   a `transport-provider` standard admission (GOVERNANCE's new-standard path) is the
   honest move, not smuggling instances into otdp.

## 8. DON'T-BUILD check

Built, and narrowly. The trigger is met by three real devices; the corpus contains a
normative sentence promising this exact lane with no mechanism behind it; the minimal
first increment is corpus text + one optional schema field + one structure schema +
two synthetic examples — no runtime, no SDK shape change, no ABI motion. The value of
increment 1 alone is deliberately small: it unblocks increments 2–3 and nothing else.
That is the issue's chosen sequencing, and the alternatives are worse — an `x-` key
declaration is barred by the corpus's own text (grounding 10), and waiting for the
gateway increment first would have it encoding an unreviewed shape.

## 9. Owner forks (surfaced, not decided)

- **F1 — version class:** 0.2.1 (recommended; additive by GOVERNANCE's shape test) vs
  0.3.0 (if "errata" reads as corrections-only). §2.
- **F2 — feature-id granularity:** per-provider ids `otdp.transport.<name>/<v>`
  (recommended — the profile precedent; a host refusal names the exact missing
  provider) vs one lane id with identity riding the pinned contract (fewer ids, blunter
  refusals). §1.1.
- **F3 — increment order:** SDK second (recommended; cheapest falsification of the
  corpus shape) vs the issue's stated gateway-second. §3.
- **F4 — grant shape:** provider-scoped `transfer` kinds (recommended; no ABI bump,
  evidence/deadline enforcement inherited) vs new HostServices methods (only if
  providers demand non-transfer semantics). §1.3, risk 2.
