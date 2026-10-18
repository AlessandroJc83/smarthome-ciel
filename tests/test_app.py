from unittest.mock import Mock


def setup_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    import app as module
    module.DATABASE_PATH = str(tmp_path / "test.db")
    module.NTFY_TOPIC = "test-topic"
    module.ENVIRONMENT = "development"
    module.NTFY_TOKEN = ""
    module.init_db()
    return module.app.test_client(), module


def test_dashboard_and_state(tmp_path, monkeypatch):
    client, _ = setup_app(tmp_path, monkeypatch)
    assert client.get("/").status_code == 200
    response = client.get("/api/state")
    assert response.status_code == 200
    assert set(response.json["rooms"]) == {"entree", "salon", "cuisine", "chambre", "salle_de_bain", "garage"}


def test_device_change_and_history(tmp_path, monkeypatch):
    client, _ = setup_app(tmp_path, monkeypatch)
    response = client.post("/api/device", json={"room": "salon", "device": "light", "on": True, "brightness": 80})
    assert response.status_code == 200
    assert response.json["devices"]["salon"]["light"]["on"] is True
    assert client.get("/api/history").json[0]["event_type"] == "commande"


def test_mode_absence(tmp_path, monkeypatch):
    client, _ = setup_app(tmp_path, monkeypatch)
    response = client.post("/api/mode", json={"mode": "Absence"})
    assert response.status_code == 200
    assert response.json["alarm_armed"] is True
    assert response.json["presence"] is False
    assert response.json["devices"]["salon"]["shutters"]["open"] is False


def test_incident_calls_ntfy(tmp_path, monkeypatch):
    client, module = setup_app(tmp_path, monkeypatch)
    sent = Mock(return_value=(1, 0, "ok"))
    monkeypatch.setattr(module, "send_push", sent)
    response = client.post("/api/incident/intrusion", json={"active": True, "notify": True})
    assert response.status_code == 200
    assert response.json["push"]["sent"] == 1
    sent.assert_called_once()


def test_ntfy_missing_topic_is_explicit_error(tmp_path, monkeypatch):
    client, module = setup_app(tmp_path, monkeypatch)
    module.NTFY_TOPIC = ""
    response = client.post("/api/ntfy/test", json={})
    assert response.status_code == 503
    assert response.json["ok"] is False


def test_ntfy_missing_token_is_explicit_error(tmp_path, monkeypatch):
    client, module = setup_app(tmp_path, monkeypatch)
    module.NTFY_TOPIC = "private-topic"
    module.ENVIRONMENT = "production"
    module.NTFY_TOKEN = ""
    response = client.post("/api/ntfy/test", json={})
    assert response.status_code == 503
    assert response.json["ok"] is False


def test_ntfy_http_error_is_reported(tmp_path, monkeypatch):
    client, module = setup_app(tmp_path, monkeypatch)
    failed = Mock()
    failed.side_effect = module.requests.RequestException("network")
    monkeypatch.setattr(module.requests, "post", failed)
    sent, _, error = module.send_push("test", "body")
    assert sent == 0
    assert "inaccessible" in error
