def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
