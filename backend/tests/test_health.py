from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_openapi_includes_mcp():
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/mcp/tools" in paths
    assert "/api/mcp/invoke" in paths
    assert "/api/mcp/rpc" in paths
    assert "/api/entities" in paths
    assert "/api/edges" in paths
    assert "/api/ontology/snapshot" in paths
    assert "/api/search" in paths
    assert "/api/graph/traverse" in paths
