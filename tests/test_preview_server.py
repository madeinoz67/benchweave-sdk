"""The SDK preview server is loopback-first, bounded and deterministic."""

from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from benchweave_sdk import preview_models, preview_server


def model() -> object:
    models = preview_models
    scenario = models.PreviewScenario(
        id="request-rejected",
        title="Request rejected",
        description="Simulated rejection",
        timestamp_strategy="fixed",
        observations=(),
        permissions=frozenset({"observer"}),
        lease_state="none",
        approval_state="not_required",
        unavailable_panels=(),
        expected_severity="warning",
        request_outcomes=(
            models.SimulatedReceipt(
                "voltage", "permission_rejected", "Simulated permission rejection"
            ),
        ),
        baseline=True,
    )
    return models.PreviewModel(
        plugin_id="dev.example.plugin",
        renderer_version="0.1.0",
        pages=(),
        scenarios=(scenario,),
    )


def get_json(url: str) -> dict[str, object] | list[object]:
    with urllib.request.urlopen(url, timeout=2) as response:
        assert response.headers["Content-Type"] == "application/json; charset=utf-8"
        assert response.headers.get("Access-Control-Allow-Origin") is None
        payload: object = json.loads(response.read())
        assert isinstance(payload, (dict, list))
        return payload


def test_server_exposes_versioned_preview_and_scenarios(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>preview</h1>", encoding="utf-8")

    with preview_server.PreviewServer(model(), tmp_path) as address:
        preview = get_json(address.url + "/api/v1/preview")
        scenarios = get_json(address.url + "/api/v1/scenarios")
        health = get_json(address.url + "/healthz")

    assert isinstance(preview, dict)
    assert preview["simulation"] is True
    assert preview["api_version"] == 1
    assert scenarios == [{"id": "request-rejected", "title": "Request rejected", "baseline": True}]
    assert health == {"ready": True, "api_version": 1}


def test_server_allows_only_configured_development_renderer_origin(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("preview", encoding="utf-8")
    with preview_server.PreviewServer(
        model(), tmp_path, allowed_origin="http://127.0.0.1:5173"
    ) as address:
        request = urllib.request.Request(
            address.url + "/api/v1/preview",
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
            assert response.headers["Vary"] == "Origin"


def test_server_returns_configured_simulated_receipt(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("preview", encoding="utf-8")

    with preview_server.PreviewServer(model(), tmp_path) as address:
        request = urllib.request.Request(
            address.url + "/api/v1/scenarios/request-rejected/requests",
            data=json.dumps({"binding_id": "voltage", "value": 13.0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            receipt = json.loads(response.read())

    assert receipt["outcome"] == "permission_rejected"
    assert receipt["simulated"] is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_wildcard_listener_is_always_rejected(host: str) -> None:
    with pytest.raises(ValueError, match="preview_unsafe_listener"):
        preview_server.validate_listener(host, allow_network=True)


def test_non_loopback_listener_requires_explicit_acknowledgement() -> None:
    with pytest.raises(ValueError, match="preview_network_acknowledgement_required"):
        preview_server.validate_listener("192.0.2.10", allow_network=False)
    preview_server.validate_listener("192.0.2.10", allow_network=True)


def test_server_does_not_serve_paths_outside_asset_root(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("preview", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("not served", encoding="utf-8")

    with (
        preview_server.PreviewServer(model(), assets) as address,
        pytest.raises(urllib.error.HTTPError) as error,
    ):
        urllib.request.urlopen(address.url + "/../secret.txt", timeout=2)

    assert error.value.code == 404


def test_preflight_options_allows_only_the_configured_renderer_origin(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("preview", encoding="utf-8")

    with preview_server.PreviewServer(
        model(), tmp_path, allowed_origin="http://127.0.0.1:5173"
    ) as address:
        request = urllib.request.Request(
            address.url + "/api/v1/scenarios/request-rejected/requests",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
            method="OPTIONS",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
            assert "POST" in response.headers["Access-Control-Allow-Methods"]
            assert "Content-Type" in response.headers["Access-Control-Allow-Headers"]

        foreign = urllib.request.Request(
            address.url + "/api/v1/preview",
            headers={"Origin": "http://127.0.0.1:9999", "Access-Control-Request-Method": "POST"},
            method="OPTIONS",
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(foreign, timeout=2)

    assert error.value.code == 403


def test_foreign_host_header_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("preview", encoding="utf-8")

    with (
        preview_server.PreviewServer(model(), tmp_path) as address,
        pytest.raises(urllib.error.HTTPError) as error,
    ):
        request = urllib.request.Request(
            address.url + "/api/v1/preview", headers={"Host": "attacker.example"}
        )
        urllib.request.urlopen(request, timeout=2)

    assert error.value.code == 403


def test_backslash_asset_paths_are_rejected_on_every_platform(tmp_path: Path) -> None:
    # A literal-backslash filename is legal on POSIX and on Windows resolves as a
    # directory escape: the guard must reject the path itself, not rely on the
    # filesystem happening to miss the file. The assets sit two levels down so
    # that the Windows reading of the request stays inside tmp_path: POSIX gets
    # the literal name beside index.html, Windows gets the file the traversal
    # would reach. (Written against tmp_path itself, the literal name lands two
    # directories above the sandbox on Windows.)
    assets = tmp_path / "deep" / "er"
    assets.mkdir(parents=True)
    (assets / "index.html").write_text("preview", encoding="utf-8")
    if os.sep == "/":
        (assets / "..\\..\\leaked.txt").write_text("leaked", encoding="utf-8")
    else:
        (tmp_path / "leaked.txt").write_text("leaked", encoding="utf-8")

    with (
        preview_server.PreviewServer(model(), assets) as address,
        pytest.raises(urllib.error.HTTPError) as error,
    ):
        urllib.request.urlopen(address.url + "/..%5C..%5Cleaked.txt", timeout=2)

    assert error.value.code == 404


def test_nul_byte_paths_are_rejected_as_not_found(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("preview", encoding="utf-8")

    with (
        preview_server.PreviewServer(model(), tmp_path) as address,
        pytest.raises(urllib.error.HTTPError) as error,
    ):
        urllib.request.urlopen(address.url + "/%00secret", timeout=2)

    assert error.value.code == 404


def test_bundled_renderer_assets_are_hash_verified_at_serve_time(tmp_path: Path) -> None:
    assert preview_server.__file__ is not None
    source = Path(preview_server.__file__).with_name("preview_assets")
    copied = tmp_path / "preview_assets"
    shutil.copytree(source, copied)

    preview_server.verify_bundled_assets(copied)

    target = copied / "site" / "index.html"
    target.write_bytes(target.read_bytes() + b"<!-- tampered -->")
    with pytest.raises(ValueError, match="preview_renderer_asset_tampered"):
        preview_server.verify_bundled_assets(copied)
