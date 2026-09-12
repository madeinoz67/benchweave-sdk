"""Public authoring surface for OTDP 0.3.0 / adapter API 1.1."""

from .interfaces import Adapter, HostServices, OperationContext

__version__ = "0.1.0"
OTDP_VERSION = "0.3.0"
ADAPTER_API_VERSION = "1.1"
__all__ = ["Adapter", "HostServices", "OperationContext"]
