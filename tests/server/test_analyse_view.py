"""I4a §1.4: the Analyse view and the report download route.

The view composes existing surfaces: the picker over the landed I3c
``capture_list`` rows (published waveform captures), the plot through the
shared wrapper's markup + the vendored hydrator, statistics through
``analysis`` (definition ``benchweave-analysis/1``, denominators stated),
the export through the ``report_export`` catalogue row (CSRF-guarded POST
per NFR-S3 — the middleware's job), and the download from the capture
root under a report-specific CSP stronger than the host default
(``script-src 'none'``: scripts cannot run in a report document).
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchweave_sdk_server.seam import StandaloneSeam
from benchweave_sdk_server.security import GuardPolicy, new_token
from benchweave_sdk_server.web import build_app

TEST_HOST = "127.0.0.1"
TEST_PORT = 8477


def write_capture(root: Path, capture_id: str, *, values: tuple[float, ...]) -> Path:
    payload = b"".join(struct.pack("<d", value) for value in values)
    event = root / capture_id
    event.mkdir(parents=True)
    (event / f"{capture_id}.f64").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (event / "manifest.json").write_text(
        json.dumps(
            {
                "capture_id": capture_id,
                "format": "waveform_f64le",
                "artifact_id": "art-" + digest,
                "byte_length": len(payload),
                "sha256": digest,
                "started_at": f"2026-10-07T12:00:00+00:00-{capture_id}",
                "sample_count": len(values),
                "sample_interval_s": 0.001,
                "unit": "V",
                "x-standalone-state": "finalised",
                "x-standalone-manifest-version": 1,
            },
            sort_keys=True,
        )
    )
    (event / "metadata.json").write_text(
        json.dumps(
            {
                "capture_id": capture_id,
                "device": {"id": "fx-device", "firmware": "1.0.0"},
                "plugin": {"package": "fx-plugin", "version": "0.1.0",
                           "descriptor_sha256": "c" * 64},
                "surface": "ui",
                "operator": "fx-op",
                "tags": [],
                "notes": "",
            },
            sort_keys=True,
        )
    )
    return event


@pytest.fixture()
def capture_root(tmp_path: Path) -> Path:
    return tmp_path / "captures"


@pytest.fixture()
def client(plugin, capture_root: Path) -> TestClient:
    from benchweave_sdk_server.session import mock_plugin_session

    seam = StandaloneSeam(
        mock_plugin_session(plugin),
        transport_kind="mock",
        capture_root=capture_root,
    )
    app = build_app(
        seam,
        policy=GuardPolicy.complete(
            bound_host=TEST_HOST,
            bound_port=TEST_PORT,
            bearer_token=new_token(),
            csrf_token=new_token(),
            operator_action_token=new_token(),
        ),
    )
    entered = TestClient(app, base_url=f"http://{TEST_HOST}:{TEST_PORT}")
    with entered:
        yield entered


def csrf_of(client: TestClient) -> str:
    page = client.get("/analyse").text
    match = re.search(r'"X-CSRF-Token":\s*"([^"]+)"', page)
    assert match is not None, "the page must render the CSRF token"
    return match.group(1)


def test_picker_lists_published_waveform_captures(
    client: TestClient, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-pick-a", values=(1.0, 2.0))
    write_capture(capture_root, "fx-pick-b", values=(3.0,))
    page = client.get("/analyse").text
    assert "fx-pick-a" in page and "fx-pick-b" in page
    assert 'name="capture"' in page
    assert 'name="lo"' in page and 'name="hi"' in page


def test_get_with_selection_renders_stats_inline(
    client: TestClient, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-inline", values=(1.0, 2.0, 3.0))
    page = client.get("/analyse", params={"capture": "fx-inline"}).text
    assert "fx-inline" in page
    assert "host-computed" in page
    assert "benchweave-analysis/1" in page
    assert "count 3" in page


def test_stats_partial_answers_htmx_post(
    client: TestClient, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-partial", values=(2.0, 4.0))
    token = csrf_of(client)
    response = client.post(
        "/analyse/stats",
        data={"capture": "fx-partial", "lo": "", "hi": ""},
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert "host-computed" in response.text
    assert "count 2" in response.text


def test_stats_post_without_csrf_refuses(client: TestClient) -> None:
    response = client.post("/analyse/stats", data={"capture": "fx-any"})
    assert response.status_code == 403
    assert response.json()["error"] == "standalone_csrf_required"


def test_export_redirects_to_the_download(
    client: TestClient, capture_root: Path
) -> None:
    write_capture(capture_root, "fx-export", values=(1.0, 5.0, 1.0))
    token = csrf_of(client)
    response = client.post(
        "/analyse/export",
        data={"capture": "fx-export", "lo": "", "hi": ""},
        headers={"X-CSRF-Token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert re.fullmatch(r"/reports/rep-[0-9a-f]{16}", location)
    downloaded = client.get(location)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("text/html")
    # The report-specific CSP: no script can run in a report document.
    csp = downloaded.headers["content-security-policy"]
    assert "script-src 'none'" in csp
    assert "style-src 'unsafe-inline'" in csp
    assert "fx-export" in downloaded.text
    # The default host CSP still governs ordinary pages (the guard was
    # tightened for reports, not weakened for everything).
    index = client.get("/")
    assert "script-src 'self'" in index.headers["content-security-policy"]


def test_download_refuses_malformed_and_unknown_ids(client: TestClient) -> None:
    for bad in (
        "/reports/../library.sqlite3",
        "/reports/not-a-report-id",
        "/reports/rep-zzzzzzzzzzzzzzzz",
    ):
        response = client.get(bad, follow_redirects=False)
        assert response.status_code == 404, bad


def test_export_refusal_renders_the_refusal(
    client: TestClient, capture_root: Path
) -> None:
    """The render-the-refusal idiom: a refused export answers with the
    code and message on the page, never a silent redirect."""
    write_capture(capture_root, "fx-there", values=(1.0,))
    token = csrf_of(client)
    page = client.post(
        "/analyse/export",
        data={"capture": ["fx-there", "fx-not-there"], "lo": "", "hi": ""},
        headers={"X-CSRF-Token": token},
    )
    assert page.status_code == 404
    assert "fx-not-there" in page.text


def test_analyse_js_is_served_under_the_inventory(client: TestClient) -> None:
    response = client.get("/assets/analyse.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    script = response.text
    # The brush is page-scoped and talks only to the wrapper's own
    # conventions: no plugin knowledge, no fetch targets beyond the host.
    assert "_bwPlot" in script
    assert "posToVal" in script
