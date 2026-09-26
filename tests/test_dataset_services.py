"""The DatasetServices protocol pins (#146 slice 1).

The protocol is a structural contract for the pinned extension contract §3
dataset services. Nothing in this SDK implements it yet (the standalone
capture-writer parity is future work; the gateway dataset path is the
intended first implementation and ships with its own slices), so what can
be pinned SDK-side is the surface itself: the seven members with their
corpus signatures, the composed twelve-member shape, the honest
no-implementation docstring, and the ``OperationContext.dataset_id``
invoke-minting note. Behavioral pins ride the gateway slices.
"""

from __future__ import annotations

import asyncio
import inspect

from benchweave_sdk.interfaces import DatasetServices, HostServices, OperationContext

SEVEN_MEMBERS = (
    "dataset_publish",
    "dataset_lookup",
    "artifact_read",
    "payload_create",
    "payload_append",
    "payload_finalise",
    "payload_abort",
)


def _members(protocol: type) -> set[str]:
    """Public members across the protocol MRO (the guide-host test's helper)."""
    names: set[str] = set()
    for klass in protocol.__mro__:
        if klass.__name__ in {"Protocol", "Generic", "object"}:
            continue
        names |= {name for name in vars(klass) if not name.startswith("_")}
    return names


def _doc(target: object) -> str:
    """Docstring as one whitespace-normalized line (pins survive reflowing)."""
    return " ".join((inspect.getdoc(target) or "").split())


def test_the_seven_dataset_members_compose_over_host_services() -> None:
    """Extension-contract §3: the dataset surface is HostServices plus
    exactly the seven named members — five inherited, seven own, twelve
    composed. A member added or lost here is a protocol-motion the corpus
    must justify."""
    assert HostServices in DatasetServices.__mro__  # issubclass refuses non-runtime protocols
    assert _members(DatasetServices) - _members(HostServices) == set(SEVEN_MEMBERS)
    assert len(_members(DatasetServices)) == 12


def test_every_dataset_member_is_an_async_context_bound_method() -> None:
    """All §3 methods are async and take the operation context — except
    ``payload_abort``, which the corpus defines without one: cleanup stays
    permitted after the deadline, and a context carries exactly that."""
    for name in SEVEN_MEMBERS:
        method = getattr(DatasetServices, name)
        assert asyncio.iscoroutinefunction(method), name
    parameters = inspect.signature(DatasetServices.payload_abort).parameters
    assert "context" not in parameters, "payload_abort is defined without a context"
    for name in SEVEN_MEMBERS[:-1]:
        parameters = inspect.signature(getattr(DatasetServices, name)).parameters
        assert "context" in parameters, name


def test_the_docstring_is_honest_that_nothing_implements_the_protocol_yet() -> None:
    """The B14 discipline, inverted: unlike CaptureServices (whose docstring
    names its first partial implementation), DatasetServices ships with no
    implementation in this SDK, and the docstring must say so rather than
    implying a runtime exists. When an implementation lands, this pin flips
    with the wording — the same motion test_capture_writer applies."""
    doc = _doc(DatasetServices)
    assert doc, "the protocol carries a docstring"
    assert "No implementation" in doc
    # The protocol must not borrow the capture writer's claim.
    assert "StandaloneCaptureWriter implements" not in doc
    # The NIT-1 honesty fix, pinned: payload_abort carries no context and
    # survives the deadline, so only the context-bound members reuse the
    # context machinery — the docstring must not overstate the reuse.
    assert "every context-bound member" in doc
    assert "every member reuses" not in doc


def test_dataset_publish_docstring_carries_the_corpus_obligations() -> None:
    """The §3 sentences that make the service safe: the dataset id is
    host-reserved (never adapter-chosen), a null context id forbids
    publishing, and inline datasets validate too."""
    doc = _doc(DatasetServices.dataset_publish).lower()
    assert "host-reserved" in doc
    assert "null" in doc
    assert "inline" in doc


def test_permission_and_bounds_notes_are_faithful_to_the_contract() -> None:
    """artifact_read names artifact_reader and its bounds; the payload
    writers name artifact_writer; finalise returns host-computed identity
    fields; abort is idempotent and post-deadline-permitted."""
    read_doc = _doc(DatasetServices.artifact_read)
    assert "artifact_reader" in read_doc
    assert "recorded length" in read_doc
    for name in ("payload_create", "payload_append", "payload_finalise"):
        assert "artifact_writer" in _doc(getattr(DatasetServices, name)), name
    assert "SHA-256" in _doc(DatasetServices.payload_finalise)
    assert "idempotent" in _doc(DatasetServices.payload_abort)


def test_operation_context_dataset_id_names_the_invoke_minting_rule() -> None:
    """The §2.5 hook: dataset_id is not a generic optional field — the host
    mints it for data-producing invoke calls and a null value forbids
    publishing. The attribute docstring must carry that note."""
    attributes = _doc(OperationContext).split("Attributes")[-1]
    dataset_note = attributes.split("dataset_id", 1)[-1].split("deadline_monotonic", 1)[0].lower()
    for phrase in ("invoke", "publish"):
        assert phrase in dataset_note, phrase
