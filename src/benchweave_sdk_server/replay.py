"""The #564/#562 replay transport: a recorded journal served as the wire.

``ByteStreamMockHost``'s second sibling (issue #564; gateway #562 work item
3). Where the byte-stream mock serves a script DERIVED from the plugin's own
``vectors.json`` — builder-generated evidence, circular by construction —
this host serves a RECORDED JOURNAL: an independent document of the
exchanges a hardware session actually observed. A plugin whose builders
reproduce the recorded wire bytes replays clean; a plugin whose builders
drifted fails loudly at the first divergent row. That is the property
builder-generated vectors cannot have, and it is the reason this host
exists.

Module contract (the replay honesty rules, pinned by ``tests/server/
test_replay.py``):

- **Load-time refusal.** A journal that is not parseable, not version ``1``,
  over the 1 MiB file bound, whose provider triple disagrees with the served
  plugin's pinned contract, or whose rows are structurally impossible
  refuses with a ``replay_journal_*:`` prefix BEFORE any conversation
  starts. The bulk rule: a send row whose inline payload is 4096 bytes or
  more must instead carry ``data_sha256`` + ``byte_length`` (exact match at
  digest granularity — sha256 plus length over the payload; a collision is
  infeasible and the row pins the length).
- **The journal is frozen evidence.** Bytes are read once at session
  construction; a file edited while the host runs never changes a
  conversation mid-serve. Each reconnect re-verifies the plugin's CURRENT
  pinned contract against the journal's provider triple — a reloaded plugin
  pinning a different contract revision refuses the reconnect.
- **Recorded times are never observed times.** The host stamps readings and
  captures on the live clock at replay time; the recording's ``recorded``
  block rides the capture sidecar as evidence metadata. No surface serves a
  recorded timestamp as an observation.
- **Exact-match discipline.** A provider row matches on the full normalized
  transaction dict; a stream send row on request bytes (inline) or on
  sha256 + length (digest form); a receive row whose bounds disagree with
  the recorded row's is a conformance failure. Every mismatch is a
  ``ConformanceError`` naming the row — never a silently served substitute.
- **Recorded failures stay failures.** A ``recorded_failure: "timeout"``
  receive row answers with the backend's ``TimeoutError`` posture and a
  ``recorded_failure: "connection"`` row answers with the
  ``ConnectionError`` posture (the recorded outcome stays the recorded
  outcome; the timing compresses to immediate). A failure row carries NO
  response — the contradiction refuses at load. Replay invents no
  certainty the recording lacks (A06).
- **The dispatch ladder is unchanged.** Grammar, then bounds, then payload,
  then liveness, then the closed transport, then the dispatch marker, then
  the row is consumed. A transmit without ``mark_dispatch_started`` is a
  ``ConformanceError``; a refused transaction leaves the conversation
  untouched, so the corrected retry hits the row it should.
- **Honest exhaustion.** The cycle unit is the minimal repeating period of
  the recorded tail with at least two full units of evidence and a
  command-bearing row in the unit, restored rotated to the recorded phase
  when a command consumes the last row (``plays`` counts the passes). A
  recording with no derivable unit — a truncated capture, or responses that
  VARY across occurrences of the same request — replays ONCE and then
  exhausts honestly: a receive past the end answers the quiet line or the
  retained-partial ``TimeoutError`` per its bounds, a transmit past the end
  is a ``ConformanceError``. The host never fabricates a row the recording
  does not contain.
- **The capture sidecar names the transport.** ``configure_capture``
  composes ``config.transport = "replay"`` and ``config.replay_journal`` (the
  journal digest and the recording's start stamp) into the sidecar metadata
  — the durable evidence names what the writer enforces, and a capture made
  over replay can never read as a live-hardware capture.

What the host does NOT do: no duplicate suppression (that sits at the
gateway boundary, A06 — the standalone host has no such surface and adds
none), no retries, no fabrication. ``dispatch_state`` is the adapter's own
honesty; this host's only contributions are never-fabricate and
never-retry.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from benchweave_sdk.interfaces import OperationContext
from benchweave_sdk.testing import ConformanceError, MockHost

from .serial import _FIELDS, WriterBackedCaptureServices, _stream_receive_bounds
from .session import (
    TRANSFER_CEILING,
    LoadedPlugin,
    PluginSession,
    transport_ceiling,
)

#: The journal file bound (issue #564 maintainer decision 3): 1 MiB. The
#: bulk-row rule keeps loader chains inside it (106 chunks x 10,000 bytes of
#: inline hex would be ~2.1 MB; as digest rows the same recording is a few
#: hundred bytes of JSON per row).
JOURNAL_BYTE_LIMIT = 1024 * 1024

#: The inline-payload bound: at this size or above, a send row MUST be
#: digest-form. "Exact match" for such rows means sha256 + byte length over
#: the outgoing bytes.
BULK_INLINE_LIMIT = 4096

_TERMINATORS = {"lf": b"\n", "crlf": b"\r\n"}

#: The receive fields per stream kind, mirroring ``_FIELDS``'s split so the
#: loader judges journal rows by the SAME field sets the backends judge
#: live transactions by (one definition family; no second frozenset).
_RECEIVE_FIELDS = {
    "stream_send": frozenset(),
    "stream_receive": frozenset({"max_bytes", "termination", "exact_bytes"}),
    "stream_exchange": frozenset({"max_bytes", "termination", "exact_bytes"}),
}


def _b64_decode(text: Any, row: str, field: str) -> bytes:
    """Decode one base64 contract-document field to ABI bytes; typed refusal."""
    if not isinstance(text, str):
        raise ValueError(
            f"replay_journal_row_shape: row {row}: {field} must be a base64 string"
        )
    try:
        return base64.b64decode(text, validate=True)
    except ValueError as exc:  # binascii.Error is a ValueError
        raise ValueError(
            f"replay_journal_row_shape: row {row}: {field} is not valid base64"
        ) from exc


def _hex_decode(text: Any, row: str, field: str) -> bytes:
    """Decode one hex field (stream payloads carry hex, the vectors.json
    convention); typed refusal naming the row."""
    if not isinstance(text, str):
        raise ValueError(
            f"replay_journal_row_shape: row {row}: {field} must be a hex string"
        )
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError(
            f"replay_journal_row_shape: row {row}: {field} is not a hex byte string"
        ) from exc


#: The composition-walk depth for _base64_props — the same 32-level cap
#: validate_transport_provider enforces on grammar subschemas (already
#: refused beyond it), so the walk here cannot be driven deeper than a
#: schema the SDK agreed to serve.
_B64_WALK_MAX_DEPTH = 32


def _base64_props(schema: dict[str, Any]) -> frozenset[str]:
    """The property names a grammar subschema carries as base64 text
    (contract-document form): the ABI carries these as bytes, so the loader
    decodes them and the serve path encodes them — one conversion rule,
    driven by the contract itself.

    The walk goes THROUGH the composition keywords (oneOf/anyOf/allOf): the
    ftdi contract's result schema is a oneOf over per-op branches whose
    properties sit one level down, and a top-level-only read served the
    journal's read_pins reply as undecoded text (found by the fold's F3
    arm). A name declared base64 in ANY branch joins the set — a
    discriminated grammar matches exactly one branch per instance, so the
    union cannot misfire on a conforming document. Not walked: ``$ref``,
    ``patternProperties`` and ``items`` (grammar payloads are plain objects
    in every corpus contract; a grammar needing those shapes extends this
    walk)."""
    found: set[str] = set()

    def visit(node: Any, depth: int) -> None:
        if depth > _B64_WALK_MAX_DEPTH or not isinstance(node, dict):
            return
        properties = node.get("properties")
        if isinstance(properties, dict):
            for name, sub in properties.items():
                if (
                    isinstance(sub, dict)
                    and sub.get("contentEncoding") == "base64"
                ):
                    found.add(name)
        for keyword in ("oneOf", "anyOf", "allOf"):
            branches = node.get(keyword)
            if isinstance(branches, list):
                for branch in branches:
                    visit(branch, depth + 1)

    visit(schema, 0)
    return frozenset(found)


@dataclass(frozen=True, slots=True)
class GrammarEntry:
    """One admitted grammar kind's compiled validators and byte-field map."""

    kind: str
    request_validator: Draft202012Validator
    result_validator: Draft202012Validator
    request_b64: frozenset[str]
    result_b64: frozenset[str]


def _grammar(contract: dict[str, Any]) -> dict[str, GrammarEntry]:
    """Compile the pinned contract's grammar: per kind, the request/result
    validators and the base64 property names. ``validate_transport_provider``
    has already meta-validated every subschema, so construction cannot fail
    on schema shape."""
    entries: dict[str, GrammarEntry] = {}
    for entry in contract["transaction_grammar"]:
        request = entry["request_schema"]
        result = entry["result_schema"]
        entries[entry["kind"]] = GrammarEntry(
            kind=entry["kind"],
            request_validator=Draft202012Validator(request),
            result_validator=Draft202012Validator(result),
            request_b64=_base64_props(request),
            result_b64=_base64_props(result),
        )
    return entries


@dataclass(frozen=True, slots=True)
class ReplayRow:
    """One validated journal row, in ABI form (bytes decoded, bounds parsed).

    ``command`` marks the request-bearing rows (provider transactions,
    stream sends, stream exchanges) — the rows a transmit matches against
    and the rows that re-arm the cycle. A receive row's ``bounds`` triple is
    its match identity; ``response`` is the recorded outcome the row
    deposits (stream kinds) or ``result`` the recorded provider result.
    ``identity``/``outcome`` are the frozen shapes the cycle derivation
    compares — never the diagnostic row names.
    """

    name: str
    kind: str
    command: bool
    expected: dict[str, Any] | None
    request: bytes | None
    digest: str | None
    byte_length: int
    bounds: tuple[int, str, int] | None
    response: bytes
    result: dict[str, Any] | None
    failure: str | None
    identity: tuple[Any, ...]
    outcome: tuple[Any, ...]


def _dict_shape(document: dict[str, Any]) -> tuple[Any, ...]:
    """A hashable shape for one ABI-form transaction/result dict (sorted by
    key; every value is str/int/bytes/None by grammar construction)."""
    return tuple((key, document[key]) for key in sorted(document))


@dataclass(frozen=True, slots=True)
class ReplayJournal:
    """A parsed, validated journal plus its derived cycle plan.

    ``sha256`` is the digest of the journal FILE bytes — the value the
    capture sidecar carries, so a sidecar names the exact recording that
    produced the capture. ``grammar`` is the compiled grammar of the pinned
    contract the journal was verified against."""

    rows: list[ReplayRow]
    establishment: int
    cycle: list[ReplayRow]
    rotate: int
    provider: dict[str, str]
    recorded: dict[str, Any]
    sha256: str
    row_count: int
    non_digest_rows: int
    grammar: dict[str, GrammarEntry]


def _outcome_check(
    row: str, bounds: tuple[int, str, int], response: bytes, failure: str | None
) -> None:
    """The recorded outcome must be one the recorded bounds could produce —
    a journal that records an impossible exchange (a 5-byte reply to an
    ``exact_bytes: 4`` receive, an unterminated run a terminator-mode receive
    returned whole) is refused at load, never served as if it were wire
    truth."""
    if failure is not None or not response:
        # A recorded failure carries no outcome; the quiet line (an empty
        # outcome) is legal under any bounds.
        return
    max_bytes, termination, exact = bounds
    if exact:
        if len(response) != exact:
            raise ValueError(
                f"replay_journal_outcome: row {row}: exact_bytes {exact} but the "
                f"recorded outcome is {len(response)} bytes"
            )
        return
    terminator = _TERMINATORS[termination]
    if len(response) > max_bytes or not response.endswith(terminator):
        raise ValueError(
            f"replay_journal_outcome: row {row}: a {len(response)}-byte outcome "
            f"without a terminating {termination!r} inside max_bytes {max_bytes} "
            "is not an outcome these bounds can produce"
        )


def _load_row(
    row: Any,
    index: int,
    names: set[str],
    grammar: dict[str, GrammarEntry],
    *,
    code: str = "replay_journal_row_shape",
) -> ReplayRow:
    """Validate and normalize one journal row into ABI form. ``code`` names
    the document family in every row-shape refusal: the journal lane's
    default keeps its historical literal byte-identical, and the #570
    provider-dialect compile passes ``standalone_vectors_row_shape`` so a
    vectors corpus's refusals name the vectors file, never "journal" — one
    validator, two documents (the anti-drift rule vectors.py states)."""
    """Validate and normalize one journal row into ABI form."""
    if not isinstance(row, dict):
        raise ValueError(f"{code}: row {index}: not an object")
    name = row.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(
            f"{code}: row {index}: name is not a non-empty string"
        )
    if name in names:
        raise ValueError(
            f"{code}: row {name}: duplicate row name "
            "(row names name the offending row in every diagnostic)"
        )
    names.add(name)
    transaction = row.get("transaction")
    if not isinstance(transaction, dict):
        raise ValueError(
            f"{code}: row {name}: transaction is not an object"
        )
    kind = transaction.get("kind")
    if not isinstance(kind, str):
        raise ValueError(f"{code}: row {name}: kind is not a string")
    failure = row.get("recorded_failure")
    if failure is not None and failure not in ("timeout", "connection"):
        raise ValueError(
            f"{code}: row {name}: recorded_failure {failure!r} "
            'is not a recorded outcome this format carries '
            '("timeout" or "connection")'
        )
    response_raw = row.get("response")

    if kind in grammar:
        # A provider row: the full transaction dict is the match identity
        # (MockHost's exact-dict posture), validated against the ADMITTED
        # grammar — never the generic table (transport-providers §3).
        entry = grammar[kind]
        if failure is not None:
            raise ValueError(
                f"{code}: row {name}: recorded_failure applies "
                "to receive rows, not provider transactions"
            )
        if not isinstance(response_raw, dict):
            raise ValueError(
                f"{code}: row {name}: a provider row's response "
                "must be an object"
            )
        document = {key: value for key, value in transaction.items() if key != "kind"}
        error = _first_schema_error(entry.request_validator, document)
        if error is not None:
            raise ValueError(
                f"{code}: row {name}: the transaction does not "
                f"satisfy the admitted {kind} grammar: {error}"
            )
        error = _first_schema_error(entry.result_validator, dict(response_raw))
        if error is not None:
            raise ValueError(
                f"{code}: row {name}: the recorded result does "
                f"not satisfy the admitted {kind} grammar: {error}"
            )
        expected: dict[str, Any] = {"kind": kind}
        for key, value in document.items():
            expected[key] = (
                _b64_decode(value, name, key) if key in entry.request_b64 else value
            )
        result: dict[str, Any] = {}
        for key, value in response_raw.items():
            result[key] = (
                _b64_decode(value, name, f"response.{key}")
                if key in entry.result_b64
                else value
            )
        return ReplayRow(
            name=name,
            kind=kind,
            command=True,
            expected=expected,
            request=None,
            digest=None,
            byte_length=0,
            bounds=None,
            response=b"",
            result=result,
            failure=None,
            identity=("provider", kind, _dict_shape(expected)),
            outcome=("result", _dict_shape(result)),
        )

    if kind in _FIELDS:
        return _load_stream_row(name, transaction, failure, response_raw, code=code)

    raise ValueError(
        f"replay_journal_kind: row {name}: kind {kind!r} is neither a generic "
        f"section 8.1 stream kind nor an admitted grammar kind "
        f"({sorted(grammar) or 'none'})"
    )


def _first_schema_error(validator: Draft202012Validator, instance: Any) -> str | None:
    """The first schema error message, or None when the instance validates."""
    for error in sorted(validator.iter_errors(instance), key=str):
        return str(error.message)
    return None


def _load_stream_row(
    name: str,
    transaction: dict[str, Any],
    failure: str | None,
    response_raw: Any,
    *,
    code: str = "replay_journal_row_shape",
) -> ReplayRow:
    """Validate one §8.1 stream row through the SHARED field sets and
    bounds definitions (one definition family for backend, mock and replay
    — no second frozenset, no second bounds ladder)."""
    kind = transaction["kind"]
    receive = _RECEIVE_FIELDS[kind]
    inline = "data" in transaction
    digest = transaction.get("data_sha256")
    byte_length = transaction.get("byte_length")
    fields = (
        frozenset({"kind"})
        | (frozenset({"data"}) if inline else frozenset())
        | (
            frozenset({"data_sha256", "byte_length"})
            if digest is not None or byte_length is not None
            else frozenset()
        )
        | receive
    )
    if set(transaction) != fields:
        raise ValueError(
            f"{code}: row {name}: not a section 8.1 stream "
            f"transaction: {sorted(transaction)}"
        )
    request: bytes | None = None
    row_digest: str | None = None
    row_length = 0
    if inline:
        if kind == "stream_receive":
            raise ValueError(
                f"{code}: row {name}: a receive row carries no "
                "outgoing data"
            )
        request = _hex_decode(transaction["data"], name, "data")
        if len(request) >= BULK_INLINE_LIMIT:
            raise ValueError(
                f"replay_journal_bulk: row {name}: inline payload is "
                f"{len(request)} bytes; sends of {BULK_INLINE_LIMIT} bytes or "
                "more must be recorded as digest-form rows "
                "(data_sha256 + byte_length)"
            )
    elif digest is not None or byte_length is not None:
        if kind == "stream_receive":
            raise ValueError(
                f"{code}: row {name}: a receive row carries no "
                "outgoing digest pair"
            )
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError(
                f"{code}: row {name}: data_sha256 is not a "
                "64-character lowercase hex digest"
            )
        if (
            not isinstance(byte_length, int)
            or isinstance(byte_length, bool)
            or byte_length < 1
        ):
            raise ValueError(
                f"{code}: row {name}: byte_length is not a "
                "positive integer"
            )
        row_digest = digest
        row_length = byte_length
    elif kind != "stream_receive":
        raise ValueError(
            f"{code}: row {name}: a send row carries either "
            "inline data or the digest pair (data_sha256 + byte_length)"
        )
    bounds: tuple[int, str, int] | None = None
    if receive:
        # Validate through the SHARED ladder (its ceiling at load time is the
        # shared 64 KiB transfer ceiling; the host clamps again against its
        # own descriptor-derived ceiling), then keep the transaction's own
        # STRING spelling — the row's match identity compares against the
        # live transaction's fields, not the ladder's terminator bytes.
        _stream_receive_bounds(transaction, TRANSFER_CEILING)
        bounds = (
            transaction["max_bytes"],
            transaction["termination"],
            transaction["exact_bytes"] or 0,
        )
    if failure is not None and kind == "stream_send":
        raise ValueError(
            f"{code}: row {name}: recorded_failure applies to "
            "receive rows, not sends"
        )
    response = b""
    if failure is None and response_raw is not None:
        if not isinstance(response_raw, dict) or set(response_raw) - {"data"}:
            raise ValueError(
                f"{code}: row {name}: a stream row's response "
                'carries at most {"data"}'
            )
        if "data" in response_raw:
            response = _hex_decode(response_raw["data"], name, "response.data")
    if failure is not None and response_raw:
        # The delta refute's residual 3: a row carrying BOTH a failure and
        # a response used to load and silently discard the response (the
        # decode above is gated on ``failure is None``) while this module
        # rejects three neighbouring contradictions. Recorded evidence
        # never vanishes without a diagnostic.
        raise ValueError(
            f"{code}: row {name}: a recorded failure row "
            "carries no response data — the failure IS the recorded outcome"
        )
    if bounds is not None:
        _outcome_check(name, bounds, response, failure)
    if kind == "stream_receive":
        return ReplayRow(
            name=name,
            kind=kind,
            command=False,
            expected=None,
            request=None,
            digest=None,
            byte_length=0,
            bounds=bounds,
            response=response,
            result=None,
            failure=failure,
            identity=(
                "recv",
                transaction["max_bytes"],
                transaction["termination"],
                transaction["exact_bytes"],
            ),
            outcome=(
                ("failure", failure) if failure else ("bytes", response)
            ),
        )
    if row_digest is not None:
        identity: tuple[Any, ...] = ("digest-send", row_digest, row_length, kind)
    else:
        identity = ("send", request, kind)
    return ReplayRow(
        name=name,
        kind=kind,
        command=True,
        expected=None,
        request=request,
        digest=row_digest,
        byte_length=row_length,
        bounds=bounds,
        response=response,
        result=None,
        failure=failure,
        identity=identity,
        outcome=("bytes", response) if failure is None else ("failure", failure),
    )


def _replay_cycle_plan(
    rows: list[ReplayRow],
) -> tuple[int, list[ReplayRow] | None, int]:
    """The minimal-period cycle plan over row identity — ``_cycle_plan``'s
    derivation with one deliberate difference: the FALLBACK is no unit at
    all. A mock may replay an ambiguous truncated capture (its guide says
    capture two full cycles); a RECORDING that cannot prove its own
    periodicity plays once and exhausts honestly — restoring a unit the
    evidence does not show would fabricate observations the hardware never
    made."""
    n = len(rows)
    shapes = [(row.identity, row.outcome) for row in rows]
    next_command = [n] * (n + 1)
    for i in range(n - 1, -1, -1):
        next_command[i] = i if rows[i].command else next_command[i + 1]
    first_command = next_command[0] if rows else n
    for period in range(1, n // 2 + 1):
        last_violation = -1
        for i in range(period, n):
            if shapes[i] != shapes[i - period]:
                last_violation = i
        earliest = max(0, last_violation - period + 1)
        for boundary in range(
            max(earliest, first_command - period + 1), n - 2 * period + 1
        ):
            if next_command[boundary] >= boundary + period:
                continue
            return boundary, list(rows[boundary : boundary + period]), (
                n - boundary
            ) % period
    return 1, None, 0


def _pinned_contract(plugin: LoadedPlugin) -> tuple[dict[str, Any], str]:
    """The plugin's pinned, verified provider contract and the digest of its
    bytes. Raises the check lane's own typed refusals (``provider_*:``)."""
    from benchweave_sdk.validation import verify_provider_pin

    descriptor_path = plugin.package_dir / "descriptor.json"
    pinned = verify_provider_pin(plugin.descriptor, descriptor_path)
    if pinned is None:
        raise ValueError(
            "replay_journal_plugin_unpinned: the replay transport serves a "
            "recorded provider journal; this plugin's descriptor declares no "
            "transport provider to verify the journal against"
        )
    relative = plugin.descriptor["transport"]["provider"]["path"]
    digest = hashlib.sha256((plugin.package_dir / relative).read_bytes()).hexdigest()
    return pinned, digest


def load_replay_journal(path: Path, plugin: LoadedPlugin) -> ReplayJournal:
    """Parse, bound and validate one journal against the plugin's pin.

    Every refusal is a ``replay_journal_*:`` ValueError raised BEFORE any
    conversation exists; the CLI maps it to exit 2 with the message, and a
    refused journal leaves the conversation untouched (there is none yet).
    """
    if not path.is_file():
        # The refute fold's F4: a directory argument reached read_bytes and
        # crashed as an uncaught IsADirectoryError (exit 1, empty message).
        # The surface owes the typed refusal, and the message names no
        # filesystem path (the EN-3 discipline).
        raise ValueError(
            "replay_journal_invalid: the journal path is not a regular file "
            "(a directory or special file cannot be a recorded journal)"
        )
    size = path.stat().st_size
    if size > JOURNAL_BYTE_LIMIT:
        raise ValueError(
            f"replay_journal_bound: the journal is {size} bytes, over the "
            f"{JOURNAL_BYTE_LIMIT}-byte (1 MiB) bound; record bulk sends as "
            "digest-form rows (data_sha256 + byte_length)"
        )
    raw = path.read_bytes()
    if len(raw) > JOURNAL_BYTE_LIMIT:  # grown between stat and read
        raise ValueError(
            f"replay_journal_bound: the journal grew past the {JOURNAL_BYTE_LIMIT}"
            "-byte (1 MiB) bound while loading; record bulk sends as "
            "digest-form rows (data_sha256 + byte_length)"
        )
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"replay_journal_invalid: not JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("replay_journal_invalid: the journal is not a JSON object")
    if document.get("journal_version") != "1":
        raise ValueError(
            f"replay_journal_version: {document.get('journal_version')!r} is not "
            'the one journal version this host serves ("1")'
        )
    recorded = document.get("recorded")
    if not isinstance(recorded, dict) or not isinstance(
        recorded.get("started_at"), str
    ) or not recorded.get("started_at") or not isinstance(recorded.get("source"), str):
        raise ValueError(
            "replay_journal_recorded: the recorded block needs a non-empty "
            "started_at (ISO-8601) and source"
        )
    extra = set(recorded) - {"started_at", "source", "operator_note", "single_owner"}
    if extra:
        raise ValueError(
            "replay_journal_recorded: the recorded block carries unknown fields "
            f"({sorted(extra)})"
        )
    if "operator_note" in recorded and not isinstance(recorded["operator_note"], str):
        raise ValueError(
            "replay_journal_recorded: operator_note is not a string"
        )
    if "single_owner" in recorded and not isinstance(recorded["single_owner"], bool):
        # Single-owner provenance (issue #564): a capture driven while another
        # session held the device is weaker evidence — the journal records
        # which kind it is, and the absence of the field says "not stated".
        raise ValueError("replay_journal_recorded: single_owner is not a boolean")
    provider = document.get("provider")
    if (
        not isinstance(provider, dict)
        or set(provider) != {"feature_id", "id", "sha256"}
        or any(not isinstance(provider[key], str) for key in provider)
    ):
        raise ValueError(
            "replay_journal_provider: the provider block is exactly "
            "{feature_id, id, sha256}, all strings"
        )
    pinned, pin_digest = _pinned_contract(plugin)
    if (
        provider["feature_id"] != pinned["feature_id"]
        or provider["id"] != pinned["id"]
        or provider["sha256"] != pin_digest
    ):
        raise ValueError(
            "replay_journal_provider_mismatch: the journal was recorded against "
            f"{provider['id']} with sha256 {provider['sha256']}, but the served "
            f"plugin pins {pinned['id']} with sha256 {pin_digest}; a journal may "
            "only replay against the contract revision it was recorded on"
        )
    grammar = _grammar(pinned)
    rows_raw = document.get("rows")
    if not isinstance(rows_raw, list) or not rows_raw:
        raise ValueError("replay_journal_rows: the journal carries no rows")
    names: set[str] = set()
    rows = [_load_row(row, index, names, grammar) for index, row in enumerate(rows_raw)]
    establishment, cycle, rotate = _replay_cycle_plan(rows)
    non_digest = sum(1 for row in rows if row.digest is None)
    return ReplayJournal(
        rows=rows,
        establishment=establishment,
        cycle=cycle or [],
        rotate=rotate,
        provider=dict(provider),
        recorded=dict(recorded),
        sha256=hashlib.sha256(raw).hexdigest(),
        row_count=len(rows),
        non_digest_rows=non_digest,
        grammar=grammar,
    )


class ReplayHost(WriterBackedCaptureServices, MockHost):
    """A demand-driven host serving one recorded journal (see the module
    contract). ``ByteStreamMockHost``'s sibling: the same real-clock
    overrides, the same ladder and exhaustion posture, with rows that are
    RECORDED exchanges — provider transactions matched on their full dict,
    stream sends on bytes or digest — and a capture sidecar that names the
    replay transport and the journal digest.

    Parameters
    ----------
    journal
        The parsed, validated :class:`ReplayJournal` (frozen evidence — the
        host never re-reads the file).
    cycles
        How many times the derived cycle may play in total (``None`` while
        serving; ``1`` is the RED control that proves the restore mechanism
        sustains reads). A journal with no derivable unit plays once
        regardless.
    max_frame_bytes
        The descriptor-derived receive ceiling (A02: the plugin's declared
        bound is the bound, clamped by the shared transfer ceiling).
    capture_root, capture_max_bytes
        The capture configuration threaded through
        :class:`WriterBackedCaptureServices`.
    """

    def __init__(
        self,
        journal: ReplayJournal,
        *,
        cycles: int | None = None,
        max_frame_bytes: int = 4096,
        capture_root: Any = None,
        capture_max_bytes: int | None = None,
    ) -> None:
        WriterBackedCaptureServices.__init__(
            self, capture_root=capture_root, capture_max_bytes=capture_max_bytes
        )
        MockHost.__init__(self, [])
        if cycles is not None and cycles < 1:
            raise ValueError("standalone_transport_cycles: cycles must be >= 1 or None")
        self._journal = journal
        self._grammar = journal.grammar
        self._ceiling = min(max_frame_bytes, TRANSFER_CEILING)
        self._rows = deque(journal.rows)
        self._cycle = deque(journal.cycle)
        self._rotate = journal.rotate
        self._cycles = cycles
        self._plays = 1
        self._armed = True
        self._inbound = bytearray()

    # -- host state surfaces -------------------------------------------------

    @property
    def plays(self) -> int:
        """How many times the recorded cycle has been made available."""
        return self._plays

    @property
    def pending(self) -> int:
        """The number of recorded rows not yet consumed."""
        return len(self._rows)

    @property
    def journal_sha256(self) -> str:
        """The digest of the journal file bytes (the sidecar's evidence)."""
        return self._journal.sha256

    def assert_complete(self) -> None:
        """Fail unless the whole recording was consumed AND the inbound
        stream drained — the same exhaustion certificate the byte-stream
        mock issues."""
        if self._rows:
            raise ConformanceError(f"{len(self._rows)} recorded rows were not consumed")
        if self._inbound:
            raise ConformanceError(
                f"{len(self._inbound)} inbound bytes remain buffered"
            )

    def monotonic(self) -> float:
        """The real monotonic clock — deadlines must expire on live time."""
        return time.monotonic()

    def utc_now(self) -> str:
        """The real UTC now, in the SDK stamp's ISO-8601 ``Z`` shape."""
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    # -- capture members (the host-stamped sidecar) ---------------------------

    def configure_capture(
        self,
        capture_id: str,
        *,
        metadata: dict[str, Any],
        max_bytes: int | None = None,
    ) -> None:
        """Arm the capture with the replay evidence composed INTO the sidecar
        (the effective-reservation precedent: the durable evidence names what
        the writer enforces — here, that this capture ran over a replayed
        recording and which recording it was)."""
        config = metadata.get("config")
        stamped = dict(
            metadata,
            config={
                **(config if isinstance(config, dict) else {}),
                "transport": "replay",
                "replay_journal": {
                    "sha256": self._journal.sha256,
                    "recorded_at": self._journal.recorded["started_at"],
                },
            },
        )
        super().configure_capture(capture_id, metadata=stamped, max_bytes=max_bytes)

    # -- the serving ladder ----------------------------------------------------

    def _check(self, context: OperationContext) -> None:
        if context.is_cancelled() or time.monotonic() >= context.deadline_monotonic:
            raise TimeoutError("Operation cancelled or expired")

    def _may_recycle(self) -> bool:
        return self._cycles is None or self._plays < self._cycles

    def _recycle_if_armed(self) -> None:
        """Restore the derived cycle unit, rotated to the recorded phase —
        only after a COMMAND row was consumed since the last restore (the
        arming rule), only while the cycle budget allows, and only when the
        journal proved a repeating unit at all (an empty unit is the
        no-derivable-cycle journal: it never restores)."""
        if self._rows or not self._armed or not self._may_recycle():
            return
        if not self._cycle:
            return
        unit = list(self._cycle)
        self._rows = deque(unit[self._rotate :] + unit[: self._rotate])
        self._plays += 1
        self._armed = False

    def _pop(self, count: int) -> bytes:
        out = bytes(self._inbound[:count])
        del self._inbound[:count]
        return out

    def _serve_receive(self, max_bytes: int, terminator: bytes, exact: int) -> bytes:
        """The backend's exact receive outcomes — inherited verbatim from the
        byte-stream mock (exact precedence, terminator within ``max_bytes``,
        the discard+ValueError on an overlong unterminated run, the quiet
        line, the retained-partial TimeoutError)."""
        if exact:
            if len(self._inbound) >= exact:
                return self._pop(exact)
        else:
            end = self._inbound[:max_bytes].find(terminator)
            if end >= 0:
                return self._pop(end + len(terminator))
            if len(self._inbound) >= max_bytes:
                del self._inbound[:max_bytes]
                raise ValueError(f"no terminator within {max_bytes} bytes")
        if not self._inbound:
            return b""
        raise TimeoutError("receive deadline expired; a partial frame stays buffered")

    def _complete_from_inbound(self, bounds: tuple[int, bytes, int]) -> bytes | None:
        """One COMPLETE frame off the inbound stream, or None when nothing
        complete is buffered (the closed-path rule — no discards, no quiet
        line, the offending run stays buffered)."""
        max_bytes, terminator, exact = bounds
        if exact:
            if len(self._inbound) >= exact:
                return self._pop(exact)
            return None
        end = self._inbound[:max_bytes].find(terminator)
        if end >= 0:
            return self._pop(end + len(terminator))
        return None

    def _next_command_row(self, transaction: dict[str, Any]) -> ReplayRow:
        """The head row a transmit must match: recycle if the recording ran
        out and the cycle may restore, then demand a COMMAND row whose shape
        fits this transaction (a provider row for a provider transaction, a
        stream row for a stream send)."""
        self._recycle_if_armed()
        if not self._rows:
            raise ConformanceError(
                "Unexpected transfer: the recording is exhausted"
            )
        row = self._rows[0]
        if not row.command:
            raise ConformanceError(
                f"row {row.name}: the recording expects a receive here, not a "
                "transmit"
            )
        wants_provider = transaction["kind"] in self._grammar
        if wants_provider != (row.expected is not None):
            raise ConformanceError(
                f"row {row.name}: the recording expects "
                f"{'a stream send' if row.expected is None else 'a provider transaction'}"
                f" here, not kind {transaction['kind']!r}"
            )
        if not wants_provider and row.kind != transaction["kind"]:
            # Kind-aware on purpose (the refute fold's NIT2): the byte-stream
            # mock matches on frame bytes alone because its FrameRow carries
            # no kind — inherited there, deliberate here. A journal row IS
            # the recorded transaction, kind included, so a stream_send must
            # not consume a recorded stream_exchange row however well the
            # bytes match: the two kinds are different conversations.
            raise ConformanceError(
                f"row {row.name}: the recording expects a {row.kind} here, "
                f"not a {transaction['kind']} (the recorded transaction kind "
                "is part of the match)"
            )
        return row

    def _match_send(self, row: ReplayRow, data: bytes) -> None:
        """Consume one head command row against the outgoing frame — inline
        rows match bytes (hex-rendered in the diagnostic), digest rows match
        sha256 + length."""
        if row.digest is not None:
            got = hashlib.sha256(data).hexdigest()
            if got != row.digest or len(data) != row.byte_length:
                raise ConformanceError(
                    f"digest mismatch at row {row.name}: expected sha256 "
                    f"{row.digest} over {row.byte_length} bytes, got {got} over "
                    f"{len(data)} bytes"
                )
        elif data != row.request:
            raise ConformanceError(
                f"frame mismatch at row {row.name}: expected "
                f"{row.request.hex() if row.request is not None else '<none>'}, "
                f"got {data.hex()}"
            )
        self._rows.popleft()

    def _validate_provider(self, transaction: dict[str, Any]) -> None:
        """Grammar-first refusal: one provider transaction against the
        ADMITTED grammar, in document form (bytes become base64 text, the
        contract's own spelling). Refused before any state changes."""
        entry = self._grammar[transaction["kind"]]
        document = {
            key: (
                base64.b64encode(value).decode("ascii")
                if key in entry.request_b64 and isinstance(value, bytes)
                else value
            )
            for key, value in transaction.items()
            if key != "kind"
        }
        error = _first_schema_error(entry.request_validator, document)
        if error is not None:
            raise ValueError(
                f"replay_transaction_grammar: the transaction does not satisfy "
                f"the admitted {transaction['kind']} grammar: {error}"
            )

    def _match_receive(self, bounds: tuple[int, str, int]) -> ReplayRow | None:
        """Match one incoming receive against the head row. A head COMMAND
        row means the recording shows a transmit here — the receive serves
        the inbound stream (the quiet line when nothing arrived), exactly as
        on real hardware, and the command row stays pending. A head receive
        row must carry the SAME bounds (a builder that changed its receive
        bounds diverges from the recording).

        A receive NEVER restores the cycle (the refute fold's F1): restoring
        here would serve the next cycle's recorded replies to receives alone
        — a conversation the recording never showed — and it would move host
        state under a drain, breaking the exhaustion certificate the mock
        preserves (restore happens in the COMMAND path only, the module
        contract's own rule)."""
        if not self._rows:
            return None
        row = self._rows[0]
        if row.command:
            return None
        recorded = row.bounds
        if recorded != bounds:
            assert recorded is not None
            raise ConformanceError(
                f"bounds mismatch at row {row.name}: the recording shows "
                f"max_bytes={recorded[0]} termination={recorded[1]!r} "
                f"exact_bytes={recorded[2]}, got max_bytes={bounds[0]} "
                f"termination={bounds[1]!r} exact_bytes={bounds[2]}"
            )
        return self._rows.popleft()

    async def transfer(
        self, transaction: dict[str, Any], context: OperationContext
    ) -> dict[str, Any]:
        kind = transaction.get("kind")
        provider_kind = isinstance(kind, str) and kind in self._grammar
        if not provider_kind and (
            kind not in _FIELDS or set(transaction) != _FIELDS[kind]
        ):
            raise ValueError(
                f"not a section 8.1 stream transaction: {sorted(transaction)}"
            )
        if provider_kind:
            self._validate_provider(transaction)
        raw_bounds: tuple[int, bytes, int] | None = None
        identity_bounds: tuple[int, str, int] | None = None
        if kind in ("stream_receive", "stream_exchange"):
            raw_bounds = _stream_receive_bounds(transaction, self._ceiling)
            identity_bounds = (
                transaction["max_bytes"],
                transaction["termination"],
                transaction["exact_bytes"] or 0,
            )
        if kind in ("stream_send", "stream_exchange") and not isinstance(
            transaction["data"], bytes
        ):
            raise ValueError("data must be bytes")
        self._check(context)
        if self.closed:
            if kind != "stream_receive":
                raise ConnectionError("Transport closed")
            # Closed-path parity with the serial backend's take: buffered
            # COMPLETE frames still deliver; a partial can never complete on
            # a dead reader, so it refuses instead of burning the deadline;
            # the resync discard runs first, closed transport or not.
            assert raw_bounds is not None
            max_bytes, terminator, exact = raw_bounds
            if (
                not exact
                and len(self._inbound) >= max_bytes
                and self._inbound[:max_bytes].find(terminator) < 0
            ):
                del self._inbound[:max_bytes]
                raise ValueError(f"no terminator within {max_bytes} bytes")
            frame = self._complete_from_inbound(raw_bounds)
            if frame is None:
                if not self._inbound:
                    raise ConnectionError("Transport closed")
                raise ConnectionError("Transport closed with a partial frame buffered")
            self.transfers.append(deepcopy(transaction))
            return {"data": frame}
        if kind != "stream_receive" and not getattr(context, "dispatched", False):
            raise ConformanceError("Transmission needs a dispatch marker")
        if kind == "stream_receive":
            assert identity_bounds is not None
            row = self._match_receive(identity_bounds)
            if row is not None and row.failure is not None:
                # The recorded failure replays honestly: the outcome class is
                # the backend's posture, compressed to immediate (the
                # recording already proved the wait); no byte is served and
                # no clean quiet-line answer upgrades the ambiguity (A06).
                if row.failure == "connection":
                    raise ConnectionError(
                        f"replay recorded_failure at row {row.name}: the "
                        "recorded exchange lost its connection after the send"
                    )
                raise TimeoutError(
                    f"replay recorded_failure at row {row.name}: the recorded "
                    "receive expired at its deadline with no complete frame"
                )
            if row is not None:
                self._inbound += row.response
            assert raw_bounds is not None
            data = self._serve_receive(*raw_bounds)
            self.transfers.append(deepcopy(transaction))
            return {"data": data}
        row = self._next_command_row(transaction)
        if provider_kind:
            if transaction != row.expected:
                raise ConformanceError(
                    f"transaction mismatch at row {row.name}: expected "
                    f"{row.expected!r}, got {transaction!r}"
                )
            self._rows.popleft()
            self._armed = True
            self.transfers.append(deepcopy(transaction))
            result = row.result
            assert result is not None
            return deepcopy(result)
        self._match_send(row, transaction["data"])
        self._armed = True
        self.transfers.append(deepcopy(transaction))
        self._inbound += row.response
        if kind == "stream_send":
            return {}
        if row.failure is not None:
            if row.failure == "connection":
                raise ConnectionError(
                    f"replay recorded_failure at row {row.name}: the "
                    "recorded exchange lost its connection after the send"
                )
            raise TimeoutError(
                f"replay recorded_failure at row {row.name}: the recorded "
                "receive expired at its deadline with no complete frame"
            )
        assert raw_bounds is not None
        return {"data": self._serve_receive(*raw_bounds)}


def replay_plugin_session(
    plugin: LoadedPlugin,
    journal_path: Path,
    *,
    capture_root: Any = None,
    capture_max_bytes: int | None = None,
) -> PluginSession:
    """A ``PluginSession`` over the replay transport: the journal is parsed
    and validated ONCE here (fail-fast — the CLI exits before serving on a
    refused journal), and each connection mints a fresh
    :class:`ReplayHost` from the frozen parse after re-verifying the CURRENT
    plugin's pinned contract against the journal's provider triple (a
    reload that re-pins a different contract revision refuses the
    reconnect, never serves a recording against a contract it was not made
    on)."""
    journal = load_replay_journal(Path(journal_path), plugin)
    settings = plugin.descriptor.get("transport", {}).get("settings", {})
    max_frame = transport_ceiling(settings)

    def factory() -> ReplayHost:
        # The CURRENT plugin, read at connect time (the late-bound
        # mock_plugin_session shape: a reload's reconnect speaks the
        # reloaded plugin). verify_provider_pin re-reads and re-hashes the
        # CURRENT pin; its typed provider_* refusals ride straight out and
        # the connect path maps them onto the standalone_plugin_connect
        # refusal family.
        pinned, pin_digest = _pinned_contract(session.plugin)
        if (
            pinned["feature_id"] != journal.provider["feature_id"]
            or pinned["id"] != journal.provider["id"]
            or pin_digest != journal.provider["sha256"]
        ):
            raise ValueError(
                "replay_journal_provider_mismatch: the journal was recorded "
                f"against {journal.provider['id']} (sha256 "
                f"{journal.provider['sha256']}), but the current plugin pins "
                f"{pinned['id']} (sha256 {pin_digest}); disconnect, re-pin the "
                "journal's contract revision, or record a new journal"
            )
        return ReplayHost(
            journal,
            max_frame_bytes=max_frame,
            capture_root=capture_root,
            capture_max_bytes=capture_max_bytes,
        )

    session: PluginSession = PluginSession(plugin, factory)
    return session
