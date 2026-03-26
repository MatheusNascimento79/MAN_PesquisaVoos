import sqlite3
import json
import os
from datetime import datetime, date

DB_PATH = os.environ.get("DB_PATH", "flights.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS search_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin_city TEXT NOT NULL DEFAULT 'São Paulo',
            origin_airports TEXT NOT NULL DEFAULT 'GRU,CGH,VCP',
            destination_city TEXT NOT NULL DEFAULT 'Paris',
            destination_airports TEXT NOT NULL DEFAULT 'CDG,ORY',
            return_origin_city TEXT NOT NULL DEFAULT 'Roma',
            return_origin_airports TEXT NOT NULL DEFAULT 'FCO,CIA',
            return_destination_city TEXT NOT NULL DEFAULT 'São Paulo',
            return_destination_airports TEXT NOT NULL DEFAULT 'GRU,CGH,VCP',
            departure_date TEXT NOT NULL DEFAULT '2026-09-09',
            return_date TEXT NOT NULL DEFAULT '2026-09-23',
            flexibility_days INTEGER NOT NULL DEFAULT 3,
            passengers INTEGER NOT NULL DEFAULT 4,
            cabin_class TEXT NOT NULL DEFAULT 'ECONOMY',
            max_stops INTEGER NOT NULL DEFAULT 1,
            excluded_countries TEXT NOT NULL DEFAULT 'US',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS search_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            config_id INTEGER NOT NULL,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            total_results INTEGER DEFAULT 0,
            sources_searched TEXT,
            errors TEXT,
            FOREIGN KEY (config_id) REFERENCES search_configs(id)
        );

        CREATE TABLE IF NOT EXISTS flight_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_run_id INTEGER NOT NULL,
            offer_hash TEXT NOT NULL,
            price_total REAL NOT NULL,
            price_per_person REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'BRL',
            outbound_date TEXT NOT NULL,
            outbound_time TEXT,
            outbound_arrival_date TEXT,
            outbound_arrival_time TEXT,
            outbound_origin TEXT NOT NULL,
            outbound_destination TEXT NOT NULL,
            outbound_stops INTEGER NOT NULL DEFAULT 0,
            outbound_connections TEXT,
            outbound_duration_minutes INTEGER,
            outbound_airlines TEXT,
            inbound_date TEXT NOT NULL,
            inbound_time TEXT,
            inbound_arrival_date TEXT,
            inbound_arrival_time TEXT,
            inbound_origin TEXT NOT NULL,
            inbound_destination TEXT NOT NULL,
            inbound_stops INTEGER NOT NULL DEFAULT 0,
            inbound_connections TEXT,
            inbound_duration_minutes INTEGER,
            inbound_airlines TEXT,
            operating_airline TEXT,
            seller TEXT,
            booking_url TEXT,
            baggage_info TEXT,
            fare_rules TEXT,
            confidence_level TEXT NOT NULL DEFAULT 'Médio',
            source TEXT NOT NULL,
            badges TEXT,
            notes TEXT,
            price_change REAL,
            price_change_pct REAL,
            collected_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (search_run_id) REFERENCES search_runs(id)
        );

        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_hash TEXT NOT NULL,
            price_total REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'BRL',
            collected_date TEXT NOT NULL,
            source TEXT NOT NULL,
            UNIQUE(offer_hash, collected_date, source)
        );

        CREATE TABLE IF NOT EXISTS search_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT NOT NULL DEFAULT 'INFO',
            message TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    # Insert default config if none exists
    cursor = conn.execute("SELECT COUNT(*) as cnt FROM search_configs")
    if cursor.fetchone()["cnt"] == 0:
        conn.execute("INSERT INTO search_configs DEFAULT VALUES")

    conn.commit()
    conn.close()


def get_active_config():
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM search_configs WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def update_config(data):
    conn = get_db()
    conn.execute("""
        UPDATE search_configs SET
            origin_city = ?, origin_airports = ?,
            destination_city = ?, destination_airports = ?,
            return_origin_city = ?, return_origin_airports = ?,
            return_destination_city = ?, return_destination_airports = ?,
            departure_date = ?, return_date = ?,
            flexibility_days = ?, passengers = ?,
            cabin_class = ?, max_stops = ?,
            excluded_countries = ?,
            updated_at = datetime('now')
        WHERE is_active = 1
    """, (
        data.get("origin_city", "São Paulo"),
        data.get("origin_airports", "GRU,CGH,VCP"),
        data.get("destination_city", "Paris"),
        data.get("destination_airports", "CDG,ORY"),
        data.get("return_origin_city", "Roma"),
        data.get("return_origin_airports", "FCO,CIA"),
        data.get("return_destination_city", "São Paulo"),
        data.get("return_destination_airports", "GRU,CGH,VCP"),
        data.get("departure_date", "2026-09-09"),
        data.get("return_date", "2026-09-23"),
        data.get("flexibility_days", 3),
        data.get("passengers", 4),
        data.get("cabin_class", "ECONOMY"),
        data.get("max_stops", 1),
        data.get("excluded_countries", "US"),
    ))
    conn.commit()
    conn.close()


def create_search_run(config_id):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO search_runs (config_id) VALUES (?)", (config_id,)
    )
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return run_id


def finish_search_run(run_id, status, total_results, sources, errors=None):
    conn = get_db()
    conn.execute("""
        UPDATE search_runs SET
            finished_at = datetime('now'),
            status = ?, total_results = ?,
            sources_searched = ?, errors = ?
        WHERE id = ?
    """, (status, total_results, sources, errors, run_id))
    conn.commit()
    conn.close()


def save_offer(run_id, offer):
    conn = get_db()
    # Calculate price change from previous day
    prev = conn.execute("""
        SELECT price_total FROM price_history
        WHERE offer_hash = ? ORDER BY collected_date DESC LIMIT 1
    """, (offer["offer_hash"],)).fetchone()

    price_change = None
    price_change_pct = None
    if prev:
        price_change = offer["price_total"] - prev["price_total"]
        if prev["price_total"] > 0:
            price_change_pct = round(
                (price_change / prev["price_total"]) * 100, 2
            )

    conn.execute("""
        INSERT INTO flight_offers (
            search_run_id, offer_hash, price_total, price_per_person, currency,
            outbound_date, outbound_time, outbound_arrival_date, outbound_arrival_time,
            outbound_origin, outbound_destination, outbound_stops, outbound_connections,
            outbound_duration_minutes, outbound_airlines,
            inbound_date, inbound_time, inbound_arrival_date, inbound_arrival_time,
            inbound_origin, inbound_destination, inbound_stops, inbound_connections,
            inbound_duration_minutes, inbound_airlines,
            operating_airline, seller, booking_url,
            baggage_info, fare_rules, confidence_level, source,
            badges, notes, price_change, price_change_pct
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        run_id, offer["offer_hash"], offer["price_total"],
        offer["price_per_person"], offer.get("currency", "BRL"),
        offer["outbound_date"], offer.get("outbound_time"),
        offer.get("outbound_arrival_date"), offer.get("outbound_arrival_time"),
        offer["outbound_origin"], offer["outbound_destination"],
        offer.get("outbound_stops", 0), offer.get("outbound_connections"),
        offer.get("outbound_duration_minutes"), offer.get("outbound_airlines"),
        offer["inbound_date"], offer.get("inbound_time"),
        offer.get("inbound_arrival_date"), offer.get("inbound_arrival_time"),
        offer["inbound_origin"], offer["inbound_destination"],
        offer.get("inbound_stops", 0), offer.get("inbound_connections"),
        offer.get("inbound_duration_minutes"), offer.get("inbound_airlines"),
        offer.get("operating_airline"), offer.get("seller"),
        offer.get("booking_url"),
        offer.get("baggage_info"), offer.get("fare_rules"),
        offer.get("confidence_level", "Médio"), offer.get("source", ""),
        json.dumps(offer.get("badges", [])),
        offer.get("notes"), price_change, price_change_pct,
    ))

    # Save to price history
    today = date.today().isoformat()
    conn.execute("""
        INSERT OR REPLACE INTO price_history (offer_hash, price_total, currency, collected_date, source)
        VALUES (?, ?, ?, ?, ?)
    """, (
        offer["offer_hash"], offer["price_total"],
        offer.get("currency", "BRL"), today, offer.get("source", ""),
    ))

    conn.commit()
    conn.close()


def get_latest_offers(filters=None):
    conn = get_db()
    # Get the latest completed search run
    run = conn.execute("""
        SELECT id, started_at, finished_at, total_results, sources_searched
        FROM search_runs WHERE status = 'completed'
        ORDER BY id DESC LIMIT 1
    """).fetchone()

    if not run:
        conn.close()
        return {"run": None, "offers": []}

    query = "SELECT * FROM flight_offers WHERE search_run_id = ?"
    params = [run["id"]]

    if filters:
        if filters.get("max_price"):
            query += " AND price_total <= ?"
            params.append(filters["max_price"])
        if filters.get("airline"):
            query += " AND operating_airline LIKE ?"
            params.append(f"%{filters['airline']}%")
        if filters.get("origin_airport"):
            query += " AND outbound_origin = ?"
            params.append(filters["origin_airport"])
        if filters.get("max_stops") is not None:
            query += " AND outbound_stops <= ? AND inbound_stops <= ?"
            params.extend([filters["max_stops"], filters["max_stops"]])
        if filters.get("hide_low_confidence"):
            query += " AND confidence_level != 'Baixo'"

    sort = filters.get("sort", "price") if filters else "price"
    sort_map = {
        "price": "price_total ASC",
        "duration": "(COALESCE(outbound_duration_minutes,9999) + COALESCE(inbound_duration_minutes,9999)) ASC",
        "stops": "(outbound_stops + inbound_stops) ASC",
        "confidence": "CASE confidence_level WHEN 'Alto' THEN 1 WHEN 'Médio' THEN 2 ELSE 3 END ASC",
    }
    query += f" ORDER BY {sort_map.get(sort, 'price_total ASC')}"

    offers = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    return {"run": dict(run), "offers": offers}


def get_price_history(offer_hash=None, days=30):
    conn = get_db()
    if offer_hash:
        rows = conn.execute("""
            SELECT * FROM price_history WHERE offer_hash = ?
            ORDER BY collected_date DESC LIMIT ?
        """, (offer_hash, days)).fetchall()
    else:
        rows = conn.execute("""
            SELECT collected_date,
                   MIN(price_total) as min_price,
                   AVG(price_total) as avg_price,
                   MAX(price_total) as max_price,
                   COUNT(*) as num_offers
            FROM price_history
            GROUP BY collected_date
            ORDER BY collected_date DESC LIMIT ?
        """, (days,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_last_run_info():
    conn = get_db()
    run = conn.execute("""
        SELECT * FROM search_runs ORDER BY id DESC LIMIT 1
    """).fetchone()
    conn.close()
    return dict(run) if run else None


def add_log(level, message, details=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO search_logs (level, message, details) VALUES (?, ?, ?)",
        (level, message, details)
    )
    conn.commit()
    conn.close()


def get_logs(limit=50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM search_logs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
