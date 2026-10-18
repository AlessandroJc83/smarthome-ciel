import json
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "data" / "smarthome.db"))
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_TOKEN = os.environ.get("NTFY_TOKEN", "").strip()
NTFY_TIMEOUT = int(os.environ.get("NTFY_TIMEOUT", "10"))
ENVIRONMENT = os.environ.get("FLASK_ENV", "development")

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("smarthome")

ROOMS = {
    "entree": {"label": "Entrée", "icon": "🚪", "temp": 19.2},
    "salon": {"label": "Salon", "icon": "🛋️", "temp": 20.4},
    "cuisine": {"label": "Cuisine", "icon": "🍳", "temp": 20.0},
    "chambre": {"label": "Chambre", "icon": "🛏️", "temp": 18.8},
    "salle_de_bain": {"label": "Salle de bain", "icon": "🛁", "temp": 21.0},
    "garage": {"label": "Garage", "icon": "🚗", "temp": 16.5},
}
DEFAULT_DEVICES = {
    room: {
        "light": {"on": False, "brightness": 70},
        "shutters": {"open": True},
        "heating": {"on": False, "target": 20},
    }
    for room in ROOMS
}
DEFAULT_STATE = {
    "mode": "Maison",
    "alarm_armed": False,
    "presence": True,
    "devices": DEFAULT_DEVICES,
    "incidents": {"intrusion": False, "fire": False, "water": False, "low_temperature": False},
}

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_connection():
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    with db_connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK (id = 1), state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, event_type TEXT NOT NULL,
                room TEXT, action TEXT NOT NULL, result TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, endpoint TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """
        )
        if db.execute("SELECT 1 FROM app_state WHERE id=1").fetchone() is None:
            db.execute("INSERT INTO app_state(id, state) VALUES(1, ?)", (json.dumps(DEFAULT_STATE),))


def get_state():
    with db_connection() as db:
        row = db.execute("SELECT state FROM app_state WHERE id=1").fetchone()
    state = json.loads(row["state"])
    return state


def save_state(state):
    with db_connection() as db:
        db.execute("UPDATE app_state SET state=? WHERE id=1", (json.dumps(state),))


def add_event(event_type, room, action, result):
    with db_connection() as db:
        db.execute(
            "INSERT INTO events(created_at,event_type,room,action,result) VALUES(?,?,?,?,?)",
            (utc_now(), event_type, room, action, result),
        )


def events(limit=80):
    with db_connection() as db:
        rows = db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def public_state():
    state = get_state()
    active = [key for key, value in state["incidents"].items() if value]
    temps = [room["temp"] for room in ROOMS.values()]
    state["active_incidents"] = active
    state["average_temperature"] = round(sum(temps) / len(temps), 1)
    state["rooms"] = {key: {**value, "temperature": temps[i]} for i, (key, value) in enumerate(ROOMS.items())}
    return state


def check_json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify(error="JSON invalide"), 400)
    return data, None


def send_push(title, body, incident=None):
    if not NTFY_TOPIC:
        logger.error("Envoi ntfy impossible: NTFY_TOPIC est absent")
        return 0, 0, "NTFY_TOPIC n'est pas configuré"
    if "/" in NTFY_TOPIC or any(char.isspace() for char in NTFY_TOPIC):
        return 0, 0, "NTFY_TOPIC doit être un nom sans slash ni espace"
    if ENVIRONMENT == "production" and not NTFY_TOKEN:
        logger.error("Envoi ntfy impossible: NTFY_TOKEN absent en production")
        return 0, 0, "NTFY_TOKEN est obligatoire en production"
    headers = {
        "Title": title,
        "Priority": "urgent" if incident in {"intrusion", "fire"} else "high",
        "Tags": "rotating_light" if incident == "intrusion" else "warning",
        "Click": "/",
    }
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"
    try:
        response = requests.post(
            f"{NTFY_SERVER}/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers=headers,
            timeout=NTFY_TIMEOUT,
        )
        if response.status_code >= 400:
            logger.error("Échec ntfy: HTTP %s", response.status_code)
            return 0, 0, f"ntfy a répondu HTTP {response.status_code}"
        return 1, 0, "ok"
    except requests.RequestException as exc:
        logger.error("Erreur réseau ntfy: %s", exc.__class__.__name__)
        return 0, 0, "serveur ntfy inaccessible"


@app.get("/")
def index():
    return render_template("index.html", ntfy_server=NTFY_SERVER, ntfy_topic=NTFY_TOPIC)


@app.get("/service-worker.js")
def service_worker():
    return app.send_static_file("service-worker.js")


@app.get("/api/state")
def api_state():
    return jsonify(public_state())


@app.get("/api/history")
def api_history():
    limit = min(max(request.args.get("limit", 80, type=int), 1), 200)
    return jsonify(events(limit))


@app.post("/api/device")
def api_device():
    data, error = check_json()
    if error:
        return error
    room, device = data.get("room"), data.get("device")
    if room not in ROOMS or device not in ("light", "shutters", "heating"):
        return jsonify(error="Pièce ou équipement inconnu"), 400
    state = get_state()
    target = state["devices"][room][device]
    if device == "light":
        if not isinstance(data.get("on"), bool):
            return jsonify(error="Le champ on doit être booléen"), 400
        target["on"] = data["on"]
        if "brightness" in data:
            target["brightness"] = min(max(int(data["brightness"]), 0), 100)
    elif device == "shutters":
        if not isinstance(data.get("open"), bool):
            return jsonify(error="Le champ open doit être booléen"), 400
        target["open"] = data["open"]
    else:
        if not isinstance(data.get("on"), bool):
            return jsonify(error="Le champ on doit être booléen"), 400
        target["on"] = data["on"]
        if "target" in data:
            target["target"] = min(max(float(data["target"]), 5), 35)
    save_state(state)
    add_event("commande", room, f"{device} modifié", "réussi")
    return jsonify(public_state())


@app.post("/api/mode")
def api_mode():
    data, error = check_json()
    if error:
        return error
    mode = data.get("mode")
    if mode not in ("Maison", "Nuit", "Absence"):
        return jsonify(error="Mode inconnu"), 400
    state = get_state()
    state["mode"] = mode
    state["presence"] = mode != "Absence"
    if mode == "Nuit":
        for room in ("salon", "cuisine", "garage"):
            state["devices"][room]["light"]["on"] = False
        state["alarm_armed"] = True
    elif mode == "Absence":
        state["alarm_armed"] = True
        for room in state["devices"].values():
            room["light"]["on"] = False
            room["shutters"]["open"] = False
    else:
        state["alarm_armed"] = False
    save_state(state)
    add_event("mode", None, f"Mode {mode}", "réussi")
    return jsonify(public_state())


INCIDENTS = {
    "intrusion": ("🚨 Intrusion détectée", "Un mouvement suspect a été détecté.", "alarme"),
    "fire": ("🔥 Fumée / incendie détecté", "Le détecteur de fumée signale un danger.", "sécurité"),
    "water": ("💧 Fuite d’eau détectée", "Une fuite d’eau est simulée dans la salle de bain.", "sécurité"),
    "low_temperature": ("❄️ Température dangereuse", "La température simulée est anormalement basse.", "confort"),
}


@app.post("/api/incident/<incident>")
def api_incident(incident):
    if incident not in INCIDENTS:
        return jsonify(error="Incident inconnu"), 404
    data, error = check_json()
    if error:
        return error
    active = data.get("active", True)
    if not isinstance(active, bool):
        return jsonify(error="active doit être booléen"), 400
    state = get_state()
    state["incidents"][incident] = active
    if active and incident == "intrusion":
        state["alarm_armed"] = True
    save_state(state)
    title, body, event_type = INCIDENTS[incident]
    sent = removed = 0
    push_result = "non demandé"
    if active and data.get("notify", True):
        sent, removed, push_error = send_push(title, body, incident)
        push_result = f"{sent} notification(s) envoyée(s)" if push_error == "ok" else f"échec: {push_error}"
    add_event(event_type, None, "activé" if active else "acquitté", push_result)
    return jsonify({**public_state(), "push": {"sent": sent, "removed": removed, "result": push_result}})


@app.post("/api/push/subscribe")
def api_subscribe():
    data, error = check_json()
    if error:
        return error
    endpoint = data.get("endpoint")
    keys = data.get("keys")
    if not isinstance(endpoint, str) or not endpoint.startswith(("https://", "http://")) or not isinstance(keys, dict):
        return jsonify(error="Souscription Push invalide"), 400
    payload = {"endpoint": endpoint, "keys": keys}
    now = utc_now()
    with db_connection() as db:
        db.execute(
            "INSERT INTO subscriptions(endpoint,payload,created_at,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(endpoint) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (endpoint, json.dumps(payload), now, now),
        )
    add_event("push", None, "souscription enregistrée", "réussi")
    return jsonify(ok=True, message="Téléphone enregistré pour les notifications.")


@app.delete("/api/push/subscribe")
def api_unsubscribe():
    data, error = check_json()
    if error:
        return error
    endpoint = data.get("endpoint")
    with db_connection() as db:
        db.execute("DELETE FROM subscriptions WHERE endpoint=?", (endpoint,))
    add_event("push", None, "souscription supprimée", "réussi")
    return jsonify(ok=True)


@app.post("/api/ntfy/test")
def api_ntfy_test():
    sent, _, error = send_push("🔔 SmartHome", "Notification de test envoyée par ntfy.")
    result = "Notification ntfy envoyée" if error == "ok" else f"échec: {error}"
    add_event("ntfy", None, "test notification", result)
    return jsonify(ok=sent == 1, message=result), (200 if sent == 1 else 503)


@app.delete("/api/history")
def api_clear_history():
    with db_connection() as db:
        db.execute("DELETE FROM events")
    return jsonify(ok=True)


init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=ENVIRONMENT == "development")
