"""Public authoring surface for OTDP device plugins.

``OTDP_VERSION`` and ``ADAPTER_API_VERSION`` are DERIVED since issue #203
slice 1: the OTDP version reads the standards lock's active row, and the
adapter API version reads that version's vendored descriptor schema
``$defs.adapter.properties.api_version`` const — the same derivation the
gateway's ``validate_identity`` performs (CON-8), relocated from a module
literal to the lock (the design's "derived constants"). They name the ACTIVE
served version; per-pin validation resolves a descriptor's own pin in
``benchweave_sdk.validation``.

The derivation is LAZY (PEP 562, #215 fix F3): deriving at import made
``import benchweave_sdk`` die on tree/lock skew — a lock row whose vendored
directory is missing crashed module import with a raw ``FileNotFoundError``
before the CLI could dispatch, so ``sync-standards --check`` could never
report the drift it exists to name. Import now always succeeds; the
constants derive on first attribute access and raise the typed refusal
(``ServedStateError``) instead.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
from typing import Any

from .interfaces import Adapter, HostServices, OperationContext
from .served import active_version
from .validation import contract_documents

try:
    __version__ = _dist_version("benchweave-sdk")
except PackageNotFoundError:  # source checkout without an installed dist
    __version__ = "0.0.0+source"
__all__ = ["Adapter", "HostServices", "OperationContext"]


def __getattr__(name: str) -> Any:
    if name == "OTDP_VERSION":
        return active_version("otdp")
    if name == "ADAPTER_API_VERSION":
        otdp = active_version("otdp")
        return str(
            contract_documents()[
                f"otdp/{otdp}/otdp-device-descriptor.schema.json"
            ]["$defs"]["adapter"]["properties"]["api_version"]["const"]
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
