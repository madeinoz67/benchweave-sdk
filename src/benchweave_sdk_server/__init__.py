"""The server host: one seam behind UI, REST and MCP.

Increment I1 (gateway issue #283): the skeleton over the SDK's scripted
mock transport, folded into the SDK distribution as the ``[server]``
extra by gateway issue #309 slice A. See the SDK README's "The server
extra" section and the design records on the gateway branches for scope
and deferrals.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

try:
    # The host rides the benchweave-sdk distribution (issue #309 slice A):
    # its version IS the distribution's, derived — never a literal (the
    # zero-literal gate's empty register for this tree depends on this).
    __version__ = _dist_version("benchweave-sdk")
except PackageNotFoundError:  # source checkout without an installed dist
    __version__ = "0.0.0+source"

__all__ = ["__version__"]
