"""The bind/unbind routes (issue #385 §1.5) and the AR-D/AR-E arms.

Host-side routes over seam methods — the scenario-select precedent (D-B1:
host state, not a catalogue op). CSRF rides the existing ``CsrfGuard``
(one arm proves the guard covers the NEW route); refusals render through
the index page's render-the-refusal idiom; the device page offers the
scan-and-re-pick action on a binding refusal.
"""

from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from benchweave_sdk_server.binding import BindingStore
from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.session import load_plugin_project
from benchweave_sdk_server.web import build_app


class LoopbackPort:
    """The per-file pyserial-shaped double (the serial suite's own)."""

    def __init__(
        self,
        inbound: bytes = b"",
        replies: dict[bytes, bytes] | None = None,
        read_timeout: float = 0.05,
    ) -> None:
        self.inbound = bytearray(inbound)
        self.replies = dict(replies or {})
        self.written: list[bytes] = []
        self.reads = 0
        self.closes = 0
        self.read_timeout = read_timeout
        self._data = threading.Event()

    def write(self, data: bytes) -> int | None:
        self.written.append(bytes(data))
        reply = self.replies.get(bytes(data))
        if reply is not None:
            self.inbound += reply
            self._data.set()
        return len(data)

    def read(self, size: int = 1) -> bytes:
        self.reads += 1
        while not self.inbound:
            if not self._data.wait(self.read_timeout):
                return b""
            self._data.clear()
        out = bytes(self.inbound[:size])
        del self.inbound[:size]
        return out

    def close(self) -> None:
        self.closes += 1
        self._data.set()


class UsbCandidate:
    def __init__(
        self,
        device: str,
        vid: int | None = 0x1A86,
        pid: int | None = 0x7523,
        serial_number: str | None = None,
    ) -> None:
        self.device = device
        self.vid = vid
        self.pid = pid
        self.serial_number = serial_number


_MATCHING = b"SDK Example,demo,SIM001,1.0.0\n"
_A = "/dev/match-a"
_B = "/dev/match-b"
_DEVICE = "example_device"


def _route_app(tmp_path: Path) -> dict[str, Any]:
    """A serial-transport app (TestClient + policy) over a binding-backed
    endpoint, with the seam exposed for direct seeding."""
    from benchweave_sdk.scaffold import create_project
    from benchweave_sdk_server.binding import binding_endpoint
    from benchweave_sdk_server.serial import (
        SerialEndpoint,
        SerialPortHooks,
        serial_plugin_session,
    )

    project = tmp_path / "proj"
    create_project(project, "example_plugin")
    plugin = load_plugin_project(project)
    ports = {
        _A: LoopbackPort(replies={b"ID?\n": _MATCHING}),
        _B: LoopbackPort(replies={b"ID?\n": _MATCHING}),
    }
    candidates = [
        UsbCandidate(_A, serial_number="SER-A"),
        UsbCandidate(_B, serial_number="SER-B"),
    ]
    opened: list[str] = []

    def open_port(device: str, settings: dict[str, Any]) -> LoopbackPort:
        opened.append(device)
        return ports[device]

    hooks = SerialPortHooks(
        enumerate_ports=lambda: list(candidates), open_port=open_port
    )
    store = BindingStore.open(tmp_path / "device-bindings.json")
    endpoint = SerialEndpoint(
        binding_endpoint(store, plugin.package, plugin.device_id, hooks.enumerate_ports)
    )
    session = serial_plugin_session(plugin, endpoint, open_port=open_port)
    seam = StandaloneSeam(
        session,
        transport_kind="serial",
        serial_ports=hooks,
        serial_endpoint=endpoint,
        bindings=store,
    )
    policy = GuardPolicy.complete(
        bound_host="127.0.0.1",
        bound_port=8477,
        bearer_token=new_token(),
        csrf_token=new_token(),
        operator_action_token=new_token(),
    )
    app = build_app(seam, policy=policy)
    return {
        "app": app,
        "policy": policy,
        "seam": seam,
        "store": store,
        "ports": ports,
        "candidates": candidates,
        "opened": opened,
        "tmp_path": tmp_path,
    }


def _client(fx: dict[str, Any]) -> TestClient:
    return TestClient(fx["app"], base_url="http://127.0.0.1:8477")


def _csrf(fx: dict[str, Any]) -> dict[str, str]:
    return {"x-csrf-token": fx["policy"].csrf_token}


def _armed(fx: dict[str, Any]) -> dict[str, str]:
    """The launch-armed page's header bag (trust-1): CSRF plus the
    per-launch operator action token — the sanctioned pick-flow credential
    set every bind/unbind through the routes now carries."""
    return {
        "x-csrf-token": fx["policy"].csrf_token,
        "x-operator-action-token": fx["policy"].operator_action_token,
    }


# --- the happy path ----------------------------------------------------------


def test_the_pick_flow_binds_and_unbinds_through_the_route(tmp_path: Path) -> None:
    fx = _route_app(tmp_path)
    with _client(fx) as client:
        scan = client.post("/discover", headers=_csrf(fx), follow_redirects=False)
        assert scan.status_code == 303
        bound = client.post(
            f"/devices/{_DEVICE}/bind",
            headers=_armed(fx),
            data={"port_path": _B},
            follow_redirects=False,
        )
        assert bound.status_code == 303
        row = fx["store"].get("example_plugin", _DEVICE)
        assert row is not None and row["port_path"] == _B
        page = client.get("/")
        assert page.status_code == 200
        assert "/dev/match-b" in page.text
        assert "SER-B" in page.text
        assert f"/devices/{_DEVICE}/unbind" in page.text
        unbound = client.post(
            f"/devices/{_DEVICE}/unbind", headers=_armed(fx), follow_redirects=False
        )
        assert unbound.status_code == 303
        assert fx["store"].rows() == []
        after = client.get("/")
        assert "Unbind" not in after.text


def test_the_unbound_host_renders_the_pick_prompt(tmp_path: Path) -> None:
    fx = _route_app(tmp_path)
    with _client(fx) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "No endpoint is bound" in page.text, (
            "the unbound serial host prompts the pick in place of the inert list"
        )


# --- AR-D: pick integrity ----------------------------------------------------


def test_ar_d_an_unconfirmed_pick_renders_and_writes_nothing(tmp_path: Path) -> None:
    fx = _route_app(tmp_path)
    with _client(fx) as client:
        client.post("/discover", headers=_csrf(fx))
        asyncio.run(fx["seam"].bind_device(_B))
        store_path = fx["tmp_path"] / "device-bindings.json"
        before = store_path.read_bytes()
        refused = client.post(
            f"/devices/{_DEVICE}/bind",
            headers=_armed(fx),
            data={"port_path": "/dev/never-scanned"},
        )
        # The M1 fold's idiom: an HTML route RENDERS its refusal (the
        # invalid_request code is the seam's; the page is the surface).
        assert refused.status_code == 200
        assert "Bind refused" in refused.text
        assert "invalid_request" in refused.text
        assert "standalone_binding_pick_unconfirmed" in refused.text
        assert store_path.read_bytes() == before


def test_ar_d_a_bind_while_connected_renders_conflict(tmp_path: Path) -> None:
    fx = _route_app(tmp_path)
    with _client(fx) as client:
        client.post("/discover", headers=_csrf(fx))
        asyncio.run(fx["seam"].bind_device(_B))
        asyncio.run(fx["seam"].call("device_connect", {"device_id": _DEVICE}))
        store_path = fx["tmp_path"] / "device-bindings.json"
        before = store_path.read_bytes()
        refused = client.post(
            f"/devices/{_DEVICE}/bind",
            headers=_armed(fx),
            data={"port_path": _A},
        )
        assert refused.status_code == 200, "the refusal renders"
        assert "conflict" in refused.text
        assert "disconnect" in refused.text
        assert store_path.read_bytes() == before


# --- AR-E: the NFR-O3 posture -------------------------------------------------


def test_ar_e_page_loads_transmit_nothing_after_a_binding_exists(
    tmp_path: Path,
) -> None:
    fx = _route_app(tmp_path)
    with _client(fx) as client:
        client.post("/discover", headers=_csrf(fx))
        asyncio.run(fx["seam"].bind_device(_B))
        before = [list(port.written) for port in fx["ports"].values()]
        index = client.get("/")
        assert index.status_code == 200
        device_page = client.get(f"/devices/{_DEVICE}")
        assert device_page.status_code == 200
        after = [list(port.written) for port in fx["ports"].values()]
        assert after == before, "page loads transmit nothing, bound or not"


def test_ar_e_bind_and_unbind_are_post_only(tmp_path: Path) -> None:
    """AR-E's POST-only clause, on the app's real routing shape: the routes
    are POST-registered, and the ``mount("/", mcp_app)`` answers a
    wrong-method GET with ITS 404 before Starlette's 405 would surface —
    either way there is no GET handler and nothing mutates."""
    fx = _route_app(tmp_path)
    with _client(fx) as client:
        assert client.get(f"/devices/{_DEVICE}/bind").status_code in (404, 405)
        assert client.get(f"/devices/{_DEVICE}/unbind").status_code in (404, 405)
        assert fx["store"].rows() == []


def test_ar_e_a_csrfless_bind_post_is_refused_by_the_guard(tmp_path: Path) -> None:
    """One arm proving the EXISTING CsrfGuard covers the NEW route: no
    ``x-csrf-token`` header, the mutation never reaches the seam."""
    fx = _route_app(tmp_path)
    with _client(fx) as client:
        client.post("/discover", headers=_csrf(fx))
        refused = client.post(
            f"/devices/{_DEVICE}/bind", data={"port_path": _B}
        )
        assert refused.status_code == 403, refused.status_code
        assert "standalone_csrf_required" in refused.text
        assert fx["store"].rows() == [], "the guard fired before any bind"


# --- the device page's re-pick action ----------------------------------------


def test_a_stale_refusal_renders_the_repick_action(tmp_path: Path) -> None:
    fx = _route_app(tmp_path)
    with _client(fx) as client:
        client.post("/discover", headers=_csrf(fx))
        asyncio.run(fx["seam"].bind_device(_B))
        fx["candidates"].remove(fx["candidates"][1])
        refused = client.post(f"/devices/{_DEVICE}/connect", headers=_csrf(fx))
        assert refused.status_code == 200, "the refusal renders, not a 500"
        assert "not_ready" in refused.text and "stale" in refused.text
        assert "SER-B" in refused.text, "the missing serial is named"
        assert "Scan and re-pick" in refused.text, "the re-pick action is offered"
        assert 'href="/"' in refused.text


def test_the_mock_host_has_no_bind_routes(client: TestClient) -> None:
    """The mock transport has no endpoint to bind: the routes do not exist
    (the scenario-route precedent — registered only where they apply). The
    CSRF header rides the request so the GUARD is not the 40x being
    asserted — routing itself must answer."""
    token = client.app.state.policy.csrf_token
    headers = {"x-csrf-token": token}
    assert client.post(
        f"/devices/{_DEVICE}/bind", headers=headers, data={"port_path": _A}
    ).status_code == 404
    assert client.post(
        f"/devices/{_DEVICE}/unbind", headers=headers
    ).status_code == 404


# --- trust-1: the operator action token ---------------------------------------
#
# The CSRF token renders into UNAUTHENTICATED HTML (every page GET serves
# it), so it is a replay-protection credential, not an operator
# credential: any loopback process scraped it in one GET and moved or
# removed the binding in one POST (probe 1's attack, reproduced end-to-end
# on the base). The fold: bind/unbind demand a credential class a page GET
# can never yield — the per-launch operator action token, minted at serve
# start and delivered OUT-OF-BAND (the serve banner and a file under the
# capture-root family); the CSRF token alone no longer suffices.


def test_a_scraped_csrf_token_alone_cannot_bind_or_unbind(
    tmp_path: Path,
) -> None:
    """Probe 1's attack through the route lane: GET / with NO credentials,
    scrape the CSRF token the page renders, POST bind/unbind with ONLY it.
    Both must refuse; the store's bytes never move."""
    fx = _route_app(tmp_path)
    with _client(fx) as client:
        client.post("/discover", headers=_csrf(fx))
        asyncio.run(fx["seam"].bind_device(_A))
        store_path = fx["tmp_path"] / "device-bindings.json"
        before = store_path.read_bytes()
        page = client.get("/")
        assert page.status_code == 200
        scraped = re.search(
            r'X-CSRF-Token&quot;: &quot;([^&]+)&quot;', page.text
        ) or re.search(r'X-CSRF-Token": "([^"]+)"', page.text)
        assert scraped is not None, "the CSRF token still renders (the probe's premise)"
        moved = client.post(
            f"/devices/{_DEVICE}/bind",
            headers={"x-csrf-token": scraped.group(1)},
            data={"port_path": _B},
            follow_redirects=False,
        )
        assert moved.status_code == 403, moved.status_code
        assert "standalone_binding_operator_token_required" in moved.text
        removed = client.post(
            f"/devices/{_DEVICE}/unbind",
            headers={"x-csrf-token": scraped.group(1)},
            follow_redirects=False,
        )
        assert removed.status_code == 403
        assert "standalone_binding_operator_token_required" in removed.text
        assert store_path.read_bytes() == before, "neither refusal moved the store"


def test_the_launch_url_token_arms_the_forms_and_survives_the_redirects(
    tmp_path: Path,
) -> None:
    """The sanctioned flow: the page view the CLI's launch URL opened (its
    query carries the token) renders the forms with BOTH headers, and the
    redirects keep the query armed so the next action (unbind, re-pick)
    still works."""
    fx = _route_app(tmp_path)
    token = fx["policy"].operator_action_token
    with _client(fx) as client:
        page = client.get("/", params={"operator_action": token})
        assert page.status_code == 200
        assert "X-Operator-Action-Token" in page.text, (
            "the armed page view plants the header on the forms"
        )
        both = {
            "x-csrf-token": fx["policy"].csrf_token,
            "x-operator-action-token": token,
        }
        scanned = client.post("/discover", headers=both, follow_redirects=False)
        assert scanned.status_code == 303
        assert f"operator_action={token}" in scanned.headers["location"], (
            "the scan's redirect keeps the launch query armed"
        )
        bound = client.post(
            f"/devices/{_DEVICE}/bind",
            headers=both,
            data={"port_path": _B},
            follow_redirects=False,
        )
        assert bound.status_code == 303
        assert f"operator_action={token}" in bound.headers["location"]
        assert fx["store"].get("example_plugin", _DEVICE) is not None
        unbound = client.post(
            f"/devices/{_DEVICE}/unbind", headers=both, follow_redirects=False
        )
        assert unbound.status_code == 303
        assert f"operator_action={token}" in unbound.headers["location"]
        assert fx["store"].rows() == []


def test_an_unarmed_page_view_renders_the_token_notice(
    tmp_path: Path,
) -> None:
    """The page a manual open reaches (no query) says WHY Bind is refused
    and where the token lives — never a silent 403 with no path forward."""
    fx = _route_app(tmp_path)
    with _client(fx) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "operator action token" in page.text
        assert "X-Operator-Action-Token" not in page.text, (
            "an unarmed view never renders the credential into HTML"
        )


def test_an_unminted_operator_token_fails_closed(tmp_path: Path) -> None:
    """The composer who never minted a token gets routes that refuse
    everything — including the empty-string header a naive equality check
    would accept against a default-empty policy field."""
    fx = _route_app(tmp_path)
    app = build_app(
        fx["seam"],
        policy=GuardPolicy.complete(
            bound_host="127.0.0.1",
            bound_port=8477,
            bearer_token=new_token(),
            csrf_token=fx["policy"].csrf_token,
        ),
    )
    with TestClient(app, base_url="http://127.0.0.1:8477") as client:
        client.post("/discover", headers=_csrf(fx))
        # Seed the operator's row through the seam directly, so the store
        # file exists for the before/after byte comparison.
        asyncio.run(fx["seam"].bind_device(_A))
        store_path = fx["tmp_path"] / "device-bindings.json"
        before = store_path.read_bytes()
        for supplied in ("", "guess", fx["policy"].operator_action_token):
            refused = client.post(
                f"/devices/{_DEVICE}/bind",
                headers={
                    "x-csrf-token": fx["policy"].csrf_token,
                    "x-operator-action-token": supplied,
                },
                data={"port_path": _B},
            )
            assert refused.status_code == 403, supplied
            assert "standalone_binding_operator_token_required" in refused.text
        assert store_path.read_bytes() == before
