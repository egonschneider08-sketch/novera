"""Full-stack, single-origin synthetic lab acceptance without real network."""

import socket

import pytest
from fastapi.testclient import TestClient
from novera.local_lab import CSP, create_local_app
from novera.research_compare import compare_scenarios, comparison_json
from novera.research_demo import report_json, run_scenario


@pytest.fixture
def local_build(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><html><head><title>Novera Lab</title></head>'
        '<body><div id="root"></div><script src="/assets/app.js"></script></body></html>',
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text(
        'document.getElementById("root").textContent="Novera LAB";',
        encoding="utf-8",
    )
    return dist


@pytest.fixture
def client(local_build):
    with TestClient(create_local_app(frontend_directory=local_build)) as app:
        yield app


def test_both_react_entrypoint_and_api_share_one_origin(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "Novera Lab" in home.text
    assert "text/html" in home.headers["content-type"]
    javascript = client.get("/assets/app.js")
    assert javascript.status_code == 200
    assert "Novera LAB" in javascript.text
    assert client.get("/api/v1/demo/scenarios/complete").json() == report_json(
        run_scenario("complete")
    )


def test_api_does_not_fall_through_to_html_on_invalid_scenario(client):
    missing = client.get("/api/v1/demo/scenarios/PETR4")
    assert missing.status_code == 404
    assert "text/html" not in missing.headers["content-type"]
    assert "Novera Lab" not in missing.text
    assert client.get("/api/v1/demo/comparison").json() == comparison_json(
        compare_scenarios()
    )


def test_both_web_and_api_are_noncacheable_and_have_same_origin_csp(client):
    for path in ("/", "/assets/app.js", "/api/v1/demo/health", "/api/v1/demo/comparison"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-security-policy"] == CSP
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-robots-tag"] == "noindex"
        assert response.headers["permissions-policy"].startswith("camera=()")
        assert "connect-src 'self'" in response.headers["content-security-policy"]


def test_block_disallowed_host_and_cross_origin_credentials(client):
    response = client.get("/", headers={"host": "other-domain.example"})
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
    cors = client.options(
        "/api/v1/demo/comparison",
        headers={
            "origin": "https://external.example",
            "access-control-request-method": "GET",
        },
    )
    assert cors.status_code == 405
    assert "access-control-allow-origin" not in cors.headers


def test_missing_assets_fail_before_server_can_start(tmp_path):
    with pytest.raises(RuntimeError, match="npm run build"):
        create_local_app(frontend_directory=tmp_path / "not-built")


def test_rejects_linked_index_file(tmp_path):
    build = tmp_path / "dist"
    build.mkdir()
    target = tmp_path / "unreviewed.html"
    target.write_text("<h1>not reviewed</h1>", encoding="utf-8")
    (build / "index.html").symlink_to(target)
    with pytest.raises(RuntimeError, match="linked"):
        create_local_app(frontend_directory=build)


def test_static_and_api_transport_is_in_process_without_network(client, monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("Novera local lab attempted an external connection")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    assert client.get("/").status_code == 200
    assert client.get("/api/v1/demo/comparison.csv").status_code == 200
    assert client.get("/api/v1/demo/scenarios/incomplete").json()["synthetic"] is True
