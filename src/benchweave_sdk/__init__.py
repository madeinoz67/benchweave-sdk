"""Public authoring surface for OTDP device plugins.

``OTDP_VERSION`` and ``ADAPTER_API_VERSION`` are DERIVED since issue #203
slice 1: the OTDP version reads the standards lock's active row, and the
adapter API version reads that version's vendored descriptor schema
``$defs.adapter.properties.api_version`` const — the same derivation the
gateway's ``validate_identity`` performs (CON-8), relocated from a module
literal to the lock (the design's "derived constants"). They name the ACTIVE
served version; per-pin validation resolves a descriptor's own pin in
``benchweave_sdk.validation``.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

from .interfaces import Adapter, HostServices, OperationContext
from .served import active_version
from .validation import contract_documents

try:
    __version__ = _dist_version("benchweave-sdk")
except PackageNotFoundError:  # source checkout without an installed dist
    __version__ = "0.0.0+source"
OTDP_VERSION = active_version("otdp")
ADAPTER_API_VERSION = str(
    contract_documents()[f"otdp/{OTDP_VERSION}/otdp-device-descriptor.schema.json"]["$defs"][
        "adapter"
    ]["properties"]["api_version"]["const"]
)
__all__ = ["Adapter", "HostServices", "OperationContext"]
