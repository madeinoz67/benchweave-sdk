"""The standalone dataset admission path (issue #589 §4, PR-3).

The ruling (issue #589, comment 2026-11-06T12:24:22Z): a plugin returns a
dataset-shaped result; the host admits it; a plugin does not call a publish
surface. This module is the surface that ruling demanded — before it, no
admission path existed to call, which is exactly how defect D4 happened.

The admission core mirrors the gateway's publish path
(``content/dataset_services.py``, read as reference semantics; nothing here
reads the gateway checkout at test or runtime) with the validation order
load-bearing: identity, then IDEMPOTENCY, then the pinned measurement
schema, then the M-structural checks (M01-M04, channels included), then
M10-correlation, then M11-scope — and only then the write. Validation
precedes any filesystem call, so a refusal leaves zero bytes under the
capture root's ``datasets/`` family; the write is ONE atomic
``manifest.json`` (temp + ``os.replace``), and manifest presence is the
publication marker.

The pinned schema, the required-key detector and the per-action validators
are CONSUMED from PR-2's resolution (``invoke_contracts.ResolvedContracts``)
— no required-key list or dataset definition is re-derived here; a corpus
sync moves nothing in this module.

Disclosed divergence from the gateway's publish path (one, per the design
record §6): the gateway routes the manifest bytes through its staged writer
so the published ``art-<sha256>`` row is the manifest's storage path; here
the single atomic ``manifest.json`` IS the storage row and there is no quota
ledger — the library row's ``sha256`` (over the canonical manifest bytes)
keeps the integrity discipline.

The D10 disclosure: the gateway still requires ``dataset_publish`` at
dispatch until GW-1 (gateway task #9). Every ``standalone_dataset_invalid:``
refusal carries the divergence sentence, and ``host_info`` carries the
``dataset_admission`` block (the design record §5's three places).

The identity binding (ADR 0606, issue #606): BOTH admission paths — the
explicit member ``dataset_publish`` and the inline admission of a
dataset-shaped invoke result — read ONE captured value per dispatch: the
operation id, the minted dataset id, the action id and the input as a
private copy, all taken before the adapter runs
(:meth:`DatasetAdmission.record_dispatch`). Neither path reads anything the
adapter holds or can rewrite. The context's ids are correlation checks
against that capture; the capture is the authority, and the dispatch RECORD
(:meth:`DatasetAdmission.dispatch_state`) is correlation history.

- The explicit member resolves the capture through the ACTIVE scope, bound
  to the dispatch context with a ``ContextVar``
  (:meth:`DatasetAdmission.active_invoke`): a call is an invoke's own only
  while that invoke is open and the call runs in it.
- The inline admission resolves it through the dispatch record, by the
  operation id the host captured in the same hook
  (:meth:`DatasetAdmission.admit_result`).
- The scope closes on that captured operation id when the adapter span ends
  (:meth:`DatasetAdmission.close_dispatch`, from the span's ``finally``): a
  rewritten ``context.operation_id`` cannot divert the close to another
  operation's scope or leave this one open, and a task that inherited the
  scope loses its authority then.
- With no dispatch record, or with no captured input (the dispatch had
  none, or the host could not copy it), admission refuses with a typed
  prefix before any write. No path falls back to a caller's object.

The guarantee's extent, stated plainly: it holds at the services boundary,
inside one host process and one dispatch context, for what the host
captured before adapter entry. It is not process isolation, and it does not
reach code that bypasses ``dataset_publish``. A publication from a bare
worker thread has no dispatch context, so it refuses; ``asyncio.to_thread``
copies the context into the worker, so a publication through it does not.
"""

from __future__ import annotations

import contextvars
import copy
import datetime
import getpass
import json
import os
import shutil
from collections.abc import Callable
from typing import Any

from benchweave_sdk.capture import _valid_capture_segment

from .invoke_contracts import ResolvedContracts
from .library import CaptureLibrary

#: The D10 disclosure sentence (issue #589 §5.3): appended to every
#: ``standalone_dataset_invalid:`` refusal so an operator staring at a
#: refused manifest knows publish-vs-admit is not the question.
_DIVERGENCE_SENTENCE = (
    "The standalone host admits or refuses datasets on the invoke result "
    "itself; the gateway additionally requires the plugin to call "
    "dataset_publish until GW-1 (issue #589 row D10)."
)

#: M03's dtype/encoding pairing and element sizes (the gateway's table,
#: verbatim — the corpus's own pairing discipline).
_DTYPE_ENCODING: dict[str, tuple[str, int | None]] = {
    "float64": ("f64le", 8),
    "int64": ("i64le", 8),
    "uint64": ("u64le", 8),
    "uint8": ("u8", 1),
    "bool": ("bool_u8", 1),
    "logic": ("logic_u8", 1),
    "complex128": ("complex_f64le", 16),
    "string": ("utf8_json", None),
}

#: The capture-root family the admitted manifests live under (one root, one
#: lockfile, one library — no second writer).
_DATASETS_FAMILY = "datasets"


def _canonical(value: Any) -> str:
    """Canonical JSON text (sorted keys, tight separators) — the idempotency
    comparison and the row's integrity digest share one form; nan/inf are
    refused at serialization (M04's backstop)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _refused(message: str) -> ValueError:
    """One ``standalone_dataset_invalid:`` ValueError carrying the
    divergence sentence (STD-4: the prefix is the contract)."""
    return ValueError(
        f"standalone_dataset_invalid: {message} {_DIVERGENCE_SENTENCE}"
    )


def _private_copy(manifest: dict[str, Any]) -> dict[str, Any]:
    """A deep JSON copy of the manifest — the admitted state is handed out
    and stored as private copies, never the caller's object."""
    copy: dict[str, Any] = json.loads(json.dumps(manifest))
    return copy


def _deep_copy_or_none(value: Any) -> Any:
    """A private deep copy of ``value``, or ``None`` when it cannot be made.

    The adapter is handed the dispatched input object and may mutate it in
    place, so nothing the admission paths compare against may hold it. A
    deep copy keeps the values JSON cannot express (NaN, Infinity, bytes,
    plain objects), so one such value does not put the echo check back on
    the live object. When no copy can be made there is no private copy at
    all: the answer is ``None``, never the caller's object, and admission
    for that dispatch refuses (``standalone_dataset_input_absent:``)."""
    try:
        return copy.deepcopy(value)
    except Exception:  # noqa: BLE001 - an object that cannot be copied has no copy
        return None


def _closed(operation_id: object) -> ValueError:
    return ValueError(
        f"standalone_dataset_invoke_closed: the invoke for operation "
        f"{operation_id!r} has closed (it finished, errored or was "
        "cancelled): its dispatch record is history, not publishing authority"
    )


def _foreign_operation(operation_id: object, made_in: str) -> ValueError:
    return ValueError(
        f"standalone_dataset_operation_mismatch: the operation context names "
        f"operation {operation_id!r}, but {made_in}: a context's ids are "
        "correlation checks against the dispatch making the call, never its "
        "authority"
    )


def _not_dispatched(operation_id: object) -> ValueError:
    return ValueError(
        f"standalone_dataset_not_dispatched: this controller has no active "
        f"host invoke for operation {operation_id!r}: it never dispatched "
        "the operation, so there is no mint to publish under"
    )


def _input_absent(operation_id: object) -> ValueError:
    return ValueError(
        f"standalone_dataset_input_absent: the dispatch record for operation "
        f"{operation_id!r} carries no captured input (the dispatch had none, "
        "or the host could not copy it), so there is nothing to check the "
        "manifest's echo fields against; a caller's object is never used in "
        "its place"
    )


def _id_mismatch(context_id: object, operation_id: str, minted: object) -> ValueError:
    return ValueError(
        f"standalone_dataset_id_mismatch: the operation context carries "
        f"dataset_id {context_id!r}, but the active invoke for operation "
        f"{operation_id!r} minted {minted!r}: the context's id is a "
        "correlation check, never the admission identity"
    )


def _write_dataset_manifest(event: Any, manifest: dict[str, Any]) -> None:
    """Write ``manifest.json`` atomically (temp + rename, the capture
    writer's own publication-marker posture). ``allow_nan=False`` matches
    every other writer; validation makes it unreachable, and the flag keeps
    a future bypass from writing a bare ``NaN`` literal to disk."""
    payload = json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False).encode()
    temp = event / "manifest.json.tmp"
    temp.write_bytes(payload)
    os.replace(temp, event / "manifest.json")


def _write_dataset_metadata(event: Any, metadata: dict[str, Any]) -> None:
    """Rewrite the ``metadata.json`` sidecar atomically (the capture
    sidecar pattern — the annotation/pin authority)."""
    payload = json.dumps(metadata, sort_keys=True).encode()
    temp = event / "metadata.json.tmp"
    temp.write_bytes(payload)
    os.replace(temp, event / "metadata.json")


class _Captured:
    """What the host bound for one dispatch before the adapter ran.

    One object serves the dispatch record and the active scope, so the
    explicit member and the inline admission cannot read different values.
    ``input`` is a private copy, or ``None`` when the host could not make
    one. Nothing here is an object the caller or the adapter holds.
    """

    __slots__ = ("action_id", "dataset_id", "input", "operation_id")

    def __init__(
        self,
        *,
        operation_id: str,
        dataset_id: str | None,
        action_id: str | None,
        input: Any,
    ) -> None:
        self.operation_id = operation_id
        self.dataset_id = dataset_id
        self.action_id = action_id
        self.input = input


class _ActiveInvoke:
    """One invoke dispatch's open scope: what the host bound before the
    adapter ran, and the state that ends its authority.

    The scope object is shared by every task that inherited the dispatch
    context, so ``closed`` is what revokes them all at once — resetting the
    variable reaches only the context that opened the scope.
    """

    __slots__ = ("captured", "closed", "controller", "token")

    def __init__(self, *, controller: DatasetAdmission, captured: _Captured) -> None:
        self.controller = controller
        self.captured = captured
        self.closed = False
        self.token: contextvars.Token[_ActiveInvoke | None] | None = None


#: The active host invoke of the CURRENT dispatch context (ADR 0606). One
#: value per task context, never one slot per controller: scopes that
#: overlap — two seams, or a dispatch nested inside another — must not see
#: each other's mints.
_ACTIVE_INVOKE: contextvars.ContextVar[_ActiveInvoke | None] = contextvars.ContextVar(
    "bws_dataset_active_invoke", default=None
)


class DatasetAdmission:
    """The admission core: validation, the this-run admitted registry and
    the capture-root persistence, over one resolved contract set.

    The registry (``admitted``) is SEAM-owned and may be shared across
    controller rebuilds — a reload rebuilds the validation surfaces (the
    incoming plugin's contracts and channels) but the manifests the host
    process admitted stay lookable up, exactly as the persisted files do.
    The open scopes are the controller's own: a scope opened on one
    controller is no authority on another.
    """

    def __init__(
        self,
        *,
        contracts: ResolvedContracts,
        channels: tuple[str, ...],
        library: Callable[[], CaptureLibrary],
        surface: Callable[[], str | None],
        admitted: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._contracts = contracts
        self._channels = frozenset(channels)
        self._library = library
        self._surface = surface
        # dataset_id -> admitted manifest (idempotency + this-run lookup)
        self._admitted: dict[str, dict[str, Any]] = (
            admitted if admitted is not None else {}
        )
        # operation_id -> what the host captured for the dispatch (the
        # mint, the action and the input as a private copy): the M10
        # correlation source and what BOTH admission paths read, mirroring
        # the gateway controller's mint_dataset_id(..., action_id=...,
        # input=...) recording.
        self._dispatch: dict[str, _Captured] = {}
        # operation_id -> the dispatch's OPEN scope (ADR 0606). Keyed by
        # operation, never one slot: a last-dispatch slot mixes scopes.
        self._open: dict[str, _ActiveInvoke] = {}

    # --- the dispatch-state recording (the seam's observe hook) -------------

    def record_dispatch(
        self,
        operation_id: str,
        *,
        dataset_id: str | None,
        action_id: str | None,
        input: Any,
    ) -> None:
        """Record one invoke dispatch — the mint, the action and the input
        as a private copy — and, in the same motion, open that dispatch's
        active scope (ADR 0606).

        The capture is what both admission paths read while the invoke is
        open and after it: nothing downstream reads the caller's input
        object. It binds to the calling dispatch context, so record it where
        the adapter will run (the mint's observe hook, before adapter entry)
        and close the scope with :meth:`close_dispatch` when the adapter
        span ends. Call it once per dispatch, with the id the host minted:
        it is the key the record and the scope are both found by.
        """
        captured = _Captured(
            operation_id=operation_id,
            dataset_id=dataset_id,
            action_id=action_id,
            input=_deep_copy_or_none(input),
        )
        self._dispatch[operation_id] = captured
        self.close_dispatch(operation_id)
        scope = _ActiveInvoke(controller=self, captured=captured)
        scope.token = _ACTIVE_INVOKE.set(scope)
        self._open[operation_id] = scope

    def close_dispatch(self, operation_id: str) -> None:
        """Close the active scope of ``operation_id`` — the adapter span's
        ``finally``, so a return, a raise and a cancellation all revoke it.

        Closing marks the scope closed, which reaches every task that
        inherited it, and takes the opening context off the scope (a scope
        the dispatch was nested in comes back). Idempotent: an operation
        with no open scope is left alone. ``operation_id`` must be the one
        the host captured before the adapter ran, never one read from the
        context afterwards: the adapter can rewrite that attribute.
        """
        scope = self._open.pop(operation_id, None)
        if scope is None:
            return
        scope.closed = True
        token = scope.token
        if token is not None and _ACTIVE_INVOKE.get() is scope:
            _ACTIVE_INVOKE.reset(token)

    def dispatch_state(self, operation_id: str) -> dict[str, Any] | None:
        """The dispatch record of ``operation_id`` — ``{dataset_id,
        action_id, input}`` — or ``None``.

        Correlation history, never authority. The input is handed out as a
        copy, so a reader of the record cannot move what the admission paths
        compare against."""
        captured = self._dispatch.get(operation_id)
        if captured is None:
            return None
        return {
            "dataset_id": captured.dataset_id,
            "action_id": captured.action_id,
            "input": _deep_copy_or_none(captured.input),
        }

    def active_invoke(self, context: Any) -> _ActiveInvoke:
        """The active host invoke a ``dataset_publish`` call is made in.

        Authority comes from WHERE the call is made — the dispatch context
        of the invoke the caller runs in — never from the context object the
        caller holds. That object's ``operation_id`` and ``dataset_id`` are
        correlation checks against the scope found there. Every refusal is
        a typed ``standalone_dataset_...:`` ``ValueError`` (STD-4), raised
        before any admission or index write.
        """
        operation_id = getattr(context, "operation_id", None)
        scope = _ACTIVE_INVOKE.get()
        if scope is None or scope.controller is not self:
            # No invoke of THIS controller is open in the calling dispatch
            # context. The operation the context names says which refusal
            # that is: active here, but the caller is not that invoke; run
            # here, and closed; or never dispatched here.
            named = operation_id if isinstance(operation_id, str) else None
            if named is not None and named in self._open:
                raise _foreign_operation(
                    named, "this call was not made in that active invoke"
                )
            if named is not None and named in self._dispatch:
                raise _closed(named)
            raise _not_dispatched(operation_id)
        bound = scope.captured
        if scope.closed:
            raise _closed(bound.operation_id)
        if operation_id != bound.operation_id:
            raise _foreign_operation(
                operation_id, f"this call was made in the invoke {bound.operation_id!r}"
            )
        context_id = getattr(context, "dataset_id", None)
        if context_id != bound.dataset_id:
            raise _id_mismatch(context_id, bound.operation_id, bound.dataset_id)
        return scope

    def admit_active(self, manifest: Any, context: Any) -> dict[str, Any]:
        """The explicit publisher's admission: resolved from the active host
        invoke the call is made in (:meth:`active_invoke`)."""
        return self._admit_captured(
            manifest, self.active_invoke(context).captured, surface=self.current_surface()
        )

    def admit_result(
        self, manifest: Any, *, operation_id: str, surface: str | None
    ) -> dict[str, Any]:
        """The inline admission: the host admits a dataset-shaped invoke
        RESULT against its own dispatch record for ``operation_id``.

        ``operation_id`` must be the one the host captured before the adapter
        ran, never one read from the context afterwards. With no record for
        the operation, or no captured input in it, this refuses before any
        admission or index write. It never falls back to the caller's input
        object."""
        captured = self._dispatch.get(operation_id)
        if captured is None:
            raise _not_dispatched(operation_id)
        return self._admit_captured(manifest, captured, surface=surface)

    def _admit_captured(
        self, manifest: Any, captured: _Captured, *, surface: str | None
    ) -> dict[str, Any]:
        """Where both admission paths end. The identity, the action and the
        input are what the host captured before the adapter ran. With no
        captured input there is nothing to check the manifest's echo fields
        against, so the publication refuses before any write."""
        if not isinstance(captured.input, dict):
            raise _input_absent(captured.operation_id)
        return self.admit(
            manifest,
            dataset_id=captured.dataset_id,
            action_id=captured.action_id,
            invoke_input=captured.input,
            surface=surface,
        )

    # --- the admission core (both paths share it) ---------------------------

    def admit(
        self,
        manifest: Any,
        *,
        dataset_id: str | None,
        action_id: str | None,
        invoke_input: Any,
        surface: str | None,
    ) -> dict[str, Any]:
        """Validate and admit one manifest; returns the immutable admitted
        manifest (a private copy). Raises :class:`ValueError` with the
        ``standalone_dataset_*:`` prefixes; an :class:`OSError` escapes only
        from the post-validation write (the caller maps it — the seam to
        ``unavailable``, the services member to the adapter's own error
        handling).

        The order is the gateway's and is load-bearing: identity, then
        idempotency, then the pinned schema, then M-structural, M10 and M11
        — only then the write. No filesystem call precedes validation.
        """
        if not isinstance(manifest, dict):
            raise _refused("the manifest must be an object")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValueError(
                "standalone_dataset_context_absent: the operation context "
                "carries no host-minted dataset_id (a non-invoke dispatch); "
                "a null value forbids publishing a dataset"
            )
        if manifest.get("dataset_id") != dataset_id:
            raise _refused(
                f"manifest dataset_id {manifest.get('dataset_id')!r} does "
                f"not carry the host-minted id {dataset_id!r}"
            )
        already = self._admitted.get(dataset_id)
        if already is not None:
            try:
                same = _canonical(manifest) == _canonical(already)
            except ValueError:
                # This branch serializes BEFORE the schema and the M-checks
                # run, so the per-lane finiteness check has not seen the
                # manifest yet — a non-finite value refuses with the prefix,
                # not the serializer's bare ValueError.
                raise _refused(
                    "M04: the manifest carries a non-finite value"
                ) from None
            if same:
                # Idempotent: no new rows, no re-routing — a repeated fetch
                # returns the admitted manifest for the operation.
                return _private_copy(already)
            raise _refused(
                f"dataset {dataset_id!r} is already admitted and immutable: "
                "a divergent manifest under a used id is refused"
            )
        error = next(
            iter(self._contracts.dataset_validator.iter_errors(manifest)), None
        )
        if error is not None:
            raise _refused(
                f"the manifest violates the pinned measurement schema at "
                f"{error.json_path}: {error.message}"
            )
        self._check_m_structural(manifest)
        self._check_m10_correlation(manifest, action_id, invoke_input)
        self._check_m11_records(manifest)
        self._check_canonicalisable(manifest)
        # A private copy: the admitted state is never the caller's object.
        admitted = _private_copy(manifest)
        self._persist(admitted, dataset_id, action_id=action_id, surface=surface)
        self._admitted[dataset_id] = admitted
        return _private_copy(admitted)

    def admitted_manifest(self, dataset_id: str) -> dict[str, Any] | None:
        """The this-run admitted manifest for ``dataset_id`` (``dataset_lookup``'s
        scope — gateway parity: the cross-principal model stays a deferral)."""
        return self._admitted.get(dataset_id)

    def current_surface(self) -> str | None:
        """The dispatch surface of the CURRENT call (provenance only)."""
        return self._surface()

    # --- the M-check subset (the gateway's implemented core, ported) --------

    def _check_m_structural(self, manifest: dict[str, Any]) -> None:
        """M01 unique/declared references, M02 length agreement, M03
        dtype/encoding consistency, M04 inline finiteness — every refusal
        names its check and the offending id."""
        axes = manifest.get("axes") or []
        axis_ids = [str(axis.get("id")) for axis in axes]
        if len(set(axis_ids)) != len(axis_ids):
            raise _refused("M01: duplicate axis ids in the manifest")
        by_id = {str(axis["id"]): axis for axis in axes}
        variables = manifest.get("variables") or []
        variable_ids = [str(variable.get("id")) for variable in variables]
        if len(set(variable_ids)) != len(variable_ids):
            raise _refused("M01: duplicate variable ids in the manifest")
        for axis in axes:
            coordinates = axis.get("coordinates")
            if isinstance(coordinates, dict) and coordinates.get("kind") == "explicit":
                values = coordinates.get("values") or []
                if len(values) != int(axis.get("length", -1)):
                    raise _refused(
                        f"M02: axis {axis['id']!r} declares length "
                        f"{axis.get('length')} but carries {len(values)} "
                        "explicit coordinates"
                    )
                self._check_finite(values, f"axis {axis['id']!r} coordinates")
            elif isinstance(coordinates, dict) and coordinates.get("kind") == "regular":
                self._check_finite(
                    [coordinates.get("start"), coordinates.get("step")],
                    f"axis {axis['id']!r} regular coordinates",
                )
        for variable in variables:
            vid = str(variable.get("id"))
            for channel_id in variable.get("channel_ids") or []:
                if channel_id not in self._channels:
                    raise _refused(
                        f"M01: variable {vid!r} references channel "
                        f"{channel_id!r} which the descriptor does not declare"
                    )
            dimensions = variable.get("dimensions") or []
            lengths: list[int] = []
            for dimension in dimensions:
                axis = by_id.get(dimension)
                if axis is None:
                    raise _refused(
                        f"M01: variable {vid!r} dimension {dimension!r} "
                        "names no axis in the manifest"
                    )
                lengths.append(int(axis["length"]))
            # M02 with the corpus's own arithmetic: the flattened element
            # count is the product of axis lengths, with SCALAR PRODUCT ONE
            # — a dimensionless variable carries exactly one element. The
            # ONLY suspension is the derived-invalid record: empty values
            # AND empty dimensions AND status invalid AND a derivation
            # marker — a shape that was never established asserts no
            # element count.
            product = 1
            for length in lengths:
                product *= length
            derived_invalid = (
                not dimensions
                and (variable.get("values") or []) == []
                and variable.get("status") == "invalid"
                and isinstance(variable.get("derivation"), dict)
            )
            dtype = str(variable.get("dtype"))
            artifact = variable.get("artifact")
            if artifact is None:
                values = variable.get("values") or []
                if not derived_invalid and len(values) != product:
                    raise _refused(
                        f"M02: variable {vid!r} carries {len(values)} inline "
                        f"values against a dimension product of {product}"
                        + (
                            " (a scalar variable carries exactly one element)"
                            if not dimensions
                            else ""
                        )
                    )
                self._check_finite(values, f"variable {vid!r} values")
            else:
                pair = _DTYPE_ENCODING.get(dtype)
                if pair is None or pair[0] != artifact.get("encoding"):
                    raise _refused(
                        f"M03: variable {vid!r} dtype {dtype!r} does not "
                        f"pair with artifact encoding "
                        f"{artifact.get('encoding')!r}"
                    )
                element_bytes = pair[1]
                if (
                    element_bytes is not None
                    and not derived_invalid
                    and int(artifact.get("byte_length", -1))
                    != product * element_bytes
                ):
                    raise _refused(
                        f"M02: variable {vid!r} artifact byte_length "
                        f"{artifact.get('byte_length')} disagrees with "
                        f"{product} elements x {element_bytes} bytes"
                    )

    @staticmethod
    def _check_finite(values: Any, label: str) -> None:
        """M04: every inline ordinary numeric is finite (invalid elements
        must be explicit nulls per the schema, never NaN/Inf smuggled in
        from Python floats)."""
        for value in values:
            if type(value) is float and (
                value != value or value in (float("inf"), float("-inf"))
            ):
                raise _refused(f"M04: {label} carry a non-finite value")

    def _check_m10_correlation(
        self, manifest: dict[str, Any], action_id: Any, invoke_input: Any
    ) -> None:
        """M10's correlation subset: the manifest's configuration_id /
        acquisition_id echo the invoke input's same-named string fields WHEN
        the dispatched action's pinned input schema declares the field — a
        schema-valid result for the wrong acquisition is rejected."""
        if not isinstance(action_id, str):
            return
        action = self._contracts.actions.get(action_id)
        if action is None or not isinstance(invoke_input, dict):
            return
        # A JSON Schema boolean schema carries no properties to declare the
        # echo fields; only an object schema arms the gate.
        schema = action.input_validator.schema
        if not isinstance(schema, dict):
            return
        declared = schema.get("properties", {})
        if not isinstance(declared, dict):
            return
        for field in ("configuration_id", "acquisition_id"):
            if field not in declared:
                continue
            expected = invoke_input.get(field)
            if isinstance(expected, str) and manifest.get(field) != expected:
                raise _refused(
                    f"M10: manifest {field} {manifest.get(field)!r} does "
                    f"not echo the invoke input's {expected!r}"
                )

    @staticmethod
    def _check_m11_records(manifest: dict[str, Any]) -> None:
        """M11, honestly scoped: no payload lane ships in this host (seam
        S4), so the finalise registry is empty and EVERY artifact-backed
        variable refuses naming the absent payload surface — inline-valued
        manifests, what an invoke-only plugin returns, are unaffected."""
        for variable in manifest.get("variables") or []:
            vid = str(variable.get("id"))
            artifact = variable.get("artifact")
            if artifact is None:
                continue
            raise _refused(
                f"M11: variable {vid!r} references artifact "
                f"{str(artifact.get('artifact_id'))!r}, but no payload "
                "surface ships in this host (the payload members are the "
                "permission-gated seam S4; inline-valued variables are the "
                "served path)"
            )

    @staticmethod
    def _check_canonicalisable(manifest: dict[str, Any]) -> None:
        """M04's backstop over the WHOLE manifest, as validation: the
        per-lane check reads only axis coordinates and variable values, and
        the pinned schema accepts a bare NaN/Infinity wherever it says
        ``number`` — a value jsonschema passes and ``allow_nan=False``
        serialization refuses. Caught here, before any filesystem call, the
        refusal is typed and leaves zero bytes; caught in the write, it
        would escape the OSError cleanup (a ValueError) and leave a ghost
        directory the rebuild silently skips."""
        try:
            _canonical(manifest)
        except ValueError:
            raise _refused(
                "M04: the manifest carries a non-finite value outside the "
                "checked axis-coordinate and variable-value lanes"
            ) from None

    # --- persistence (validation has already passed) ------------------------

    def _persist(
        self,
        manifest: dict[str, Any],
        dataset_id: str,
        *,
        action_id: str | None,
        surface: str | None,
    ) -> None:
        """Persist one admitted manifest under ``<root>/datasets/<segment>/``
        with the provenance sidecar, and record the library row. An existing
        segment refuses BEFORE any write (a mint collision must not destroy
        what is already on disk); a write failure removes only the directory
        this call created, best-effort, so a refusal or a failed write
        leaves no partial dataset directory behind."""
        segment = dataset_id.replace(":", "-", 1)
        if not _valid_capture_segment(segment):
            # Unreachable for host-minted ids (every mint starts "ds:"), and
            # that is WHY it refuses rather than sanitising: the segment
            # gate is capture.py's own single authority over root segments.
            raise _refused(
                f"the minted dataset id {dataset_id!r} does not map to a "
                "safe capture-root segment"
            )
        library = self._library()
        event = library.root / _DATASETS_FAMILY / segment
        try:
            # exist_ok is deliberately absent: an existing segment is a mint
            # collision with what is already on disk (the mint is 32 bits of
            # uuid4 hex — an event, not an impossibility), and refusing it
            # here is what keeps the cleanup below from destroying the prior
            # dataset.
            event.mkdir(parents=True)
        except FileExistsError:
            raise _refused(
                f"the segment {segment!r} for dataset {dataset_id!r} already "
                "exists under the capture root: the mint collided with an "
                "admitted dataset, and the prior dataset is untouched"
            ) from None
        try:
            _write_dataset_manifest(event, manifest)
            try:
                operator = getpass.getuser()
            except Exception:  # noqa: BLE001 - an environment with no user name
                operator = "unknown"
            metadata: dict[str, Any] = {
                "dataset_id": dataset_id,
                "action_id": action_id,
                "surface": surface,
                "operator": operator,
                "project": None,
                "pinned": False,
                "tags": [],
                "notes": "",
                "at": datetime.datetime.now(datetime.UTC).isoformat(),
            }
            _write_dataset_metadata(event, metadata)
            library.record_dataset(dataset_id, manifest, metadata)
        except OSError:
            shutil.rmtree(event, ignore_errors=True)
            raise

    # --- the explicit protocol surface (the two base members) ---------------

    def attach(self, base: Any) -> Any:
        """Compose this admission core's two base ``DatasetServices`` members
        onto any services base as a transparent delegating wrapper (member
        presence is the ecosystem's established capability probe — the
        ``LinkControlServices`` precedent). The payload members (S4) never
        attach here."""
        return _DatasetServicesView(base, self)


class _DatasetServicesView:
    """The delegating wrapper: every base member resolves through
    ``__getattr__`` (the capture duck-checks pass through untouched), with
    ``dataset_publish`` and ``dataset_lookup`` as the added members."""

    def __init__(self, base: Any, admission: DatasetAdmission) -> None:
        self._base = base
        self._admission = admission

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    async def dataset_publish(
        self, manifest: dict[str, Any], context: Any
    ) -> dict[str, Any]:
        """Validate and admit one manifest for the ACTIVE host invoke this
        call is made in — the explicit surface pre-ruling plugins and upload
        actions use; the inline result path shares the same core.

        Everything admission compares against is what the host captured for
        that invoke before the adapter ran (ADR 0606). The ``context`` the
        caller supplies two correlation checks — its ``operation_id`` and
        its ``dataset_id`` — and nothing else: a rewritten id, another
        operation's id, an operation that was never dispatched, a closed
        invoke and a dispatch with no captured input each refuse here,
        before any admission or index write.
        """
        dataset_id = getattr(context, "dataset_id", None)
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValueError(
                "standalone_dataset_context_absent: the operation context "
                "carries no host-minted dataset_id (a non-invoke dispatch); "
                "a null value forbids publishing a dataset"
            )
        return self._admission.admit_active(manifest, context)

    async def dataset_lookup(self, dataset_id: str, context: Any) -> dict[str, Any]:
        """The admitted manifest for ``dataset_id``, THIS host process's
        admissions only (gateway scope parity — the cross-principal
        authorization model stays the gateway's own deferral, mirrored)."""
        admitted = self._admission.admitted_manifest(dataset_id)
        if admitted is None:
            raise ValueError(
                f"standalone_dataset_unknown: unknown dataset id for this "
                f"run: {dataset_id!r} (dataset_lookup serves the manifests "
                "this host process admitted)"
            )
        return _private_copy(admitted)


def attach_dataset_members(services: Any, *, controller: DatasetAdmission) -> Any:
    """Compose the two base dataset members onto ``services`` (the design
    record §3's explicit-admission surface; the seam installs the wrapper
    whenever the invoke lane is armed, mirroring the gateway's
    base-members-always rule)."""
    return controller.attach(services)
