"""
MAN PesquisaVoos - Flight Price Monitor
Main Flask application with API and scheduler.
"""

import os
import threading
import logging
from datetime import datetime

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from models.database import (
    init_db, get_active_config, update_config,
    get_latest_offers, get_price_history, get_last_run_info,
    get_logs,
)
from agent.flight_search import run_search

load_dotenv()

app = Flask(__name__)
CORS(app)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Scheduler ────────────────────────────────────────────────────

SEARCH_HOUR = int(os.environ.get("SEARCH_HOUR", "6"))
_search_lock = threading.Lock()


def scheduled_search():
    with app.app_context():
        if _search_lock.locked():
            logger.info("Search already running, skipping scheduled run.")
            return
        with _search_lock:
            try:
                run_search(is_manual=False)
            except Exception as e:
                logger.error(f"Scheduled search failed: {e}")


# ─── Pages ────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ─── API Endpoints ────────────────────────────────────────────────

@app.route("/api/offers")
def api_offers():
    filters = {}
    if request.args.get("max_price"):
        filters["max_price"] = float(request.args["max_price"])
    if request.args.get("airline"):
        filters["airline"] = request.args["airline"]
    if request.args.get("origin_airport"):
        filters["origin_airport"] = request.args["origin_airport"]
    if request.args.get("max_stops") is not None and request.args.get("max_stops") != "":
        filters["max_stops"] = int(request.args["max_stops"])
    if request.args.get("hide_low_confidence"):
        filters["hide_low_confidence"] = True
    if request.args.get("sort"):
        filters["sort"] = request.args["sort"]

    data = get_latest_offers(filters if filters else None)
    return jsonify(data)


@app.route("/api/config", methods=["GET"])
def api_get_config():
    config = get_active_config()
    return jsonify(config)


@app.route("/api/config", methods=["POST"])
def api_update_config():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    update_config(data)
    return jsonify({"status": "ok", "config": get_active_config()})


@app.route("/api/search", methods=["POST"])
def api_trigger_search():
    if _search_lock.locked():
        return jsonify({"status": "already_running"}), 409

    def _run():
        with app.app_context():
            with _search_lock:
                run_search(is_manual=True)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/history")
def api_history():
    offer_hash = request.args.get("offer_hash")
    days = int(request.args.get("days", 30))
    data = get_price_history(offer_hash, days)
    return jsonify(data)


@app.route("/api/status")
def api_status():
    last_run = get_last_run_info()
    config = get_active_config()
    return jsonify({
        "last_run": last_run,
        "config": config,
        "search_locked": _search_lock.locked(),
    })


@app.route("/api/logs")
def api_logs():
    limit = int(request.args.get("limit", 50))
    return jsonify(get_logs(limit))


# ─── Init ─────────────────────────────────────────────────────────

with app.app_context():
    init_db()

if os.environ.get("ENABLE_SCHEDULER", "true").lower() == "true":
    scheduler = BackgroundScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        scheduled_search,
        trigger=CronTrigger(hour=SEARCH_HOUR, minute=0),
        id="daily_flight_search",
        replace_existing=True,
    )
    scheduler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
