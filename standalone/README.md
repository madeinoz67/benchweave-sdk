# benchweave-standalone

A standalone BenchWeave host: one process that loads a device plugin's adapter,
drives it over a scripted (I1) transport, and serves a server-rendered HTMX UI,
a JSON REST API and an in-process MCP endpoint over one operations seam — with
no gateway present.

Every page carries the banner **STANDALONE — no gateway**: there are no leases,
policy, approvals, procedures or run records behind anything this process
serves (`host_info` states the same absent guarantees for agents).

This is increment I1 of the standalone web UI plan (gateway issue #283): the
skeleton over the SDK's `MockHost`-class scripted transport. Hardware serial
transport, presentation-manifest rendering, capture and analysis land in later
increments; operations the increment does not implement are refused
(`unavailable`, `reason: increment_deferral`) and listed as deferred in
`host_info`.

## Run

```sh
uv sync
uv run benchweave-standalone serve /path/to/plugin-project --transport mock --port 8477 --no-open
```

The startup prints the URL and the per-launch bearer token REST mutations and
MCP-over-HTTP calls require. `benchweave-standalone mcp /path/to/plugin-project`
runs the same MCP server over stdio with no HTTP listener.

## Layout

- `src/benchweave_standalone/catalogue.py` — the closed operation catalogue
  (18 SW-10 names; six implemented in I1) and the interface-0.1.0 error code set.
- `src/benchweave_standalone/seam.py` — `StandaloneSeam.call`, the only
  mutation path; REST, HTML and MCP are adapters over it.
- `src/benchweave_standalone/session.py` — the adapter lifecycle and
  per-operation contexts bounded by the descriptor's own operation policy.
- `src/benchweave_standalone/transport.py` — `LoopingMockHost`, the recycling
  scripted transport with real clocks.
- `src/benchweave_standalone/web.py` / `security.py` — the app factory and the
  individual guard middlewares (trusted-Host, CSRF, bearer, MCP token+Origin,
  body cap, CSP).
- `src/benchweave_standalone/mcp.py` — the `bws_v1_*` tools with schemas pinned
  from the catalogue, plus the `--authoring`-only scaffold/check tools.
- `src/benchweave_standalone/ui_assets/` — tokens/themes vendored byte-for-byte
  from the canonical UI corpus plus htmx, digest-verified at serve time.

## Safety posture

The SDK wheel is untouched by construction: nothing under the SDK package
moves for this distribution. Plugin code runs in-process with full authority
(same trust boundary as the gateway); the UI names the plugin package and
version it loaded. Listener rules reuse the SDK preview server's: loopback by
default, wildcard refused, non-loopback only with `--allow-network`.
