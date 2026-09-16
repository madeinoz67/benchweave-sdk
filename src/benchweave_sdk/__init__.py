"""Public authoring surface for OTDP 0.1.0 / adapter API 0.1.0."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

from .interfaces import Adapter, HostServices, OperationContext

try:
    __version__ = _dist_version("benchweave-sdk")
except PackageNotFoundError:  # source checkout without an installed dist
    __version__ = "0.0.0+source"
OTDP_VERSION = "0.1.0"
ADAPTER_API_VERSION = "0.1.0"
__all__ = ["Adapter", "HostServices", "OperationContext"]
