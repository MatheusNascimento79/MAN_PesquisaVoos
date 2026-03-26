"""
Flight Search Agent - searches Google Flights via SerpAPI.

SerpAPI free tier: 100 searches/month.
Strategy: 2 API calls per date combo (outbound + inbound).
With 3 date combos/day = 6 calls/day = ~180/month.
We limit to 1-2 combos/day for daily auto-search (2-4 calls/day = ~90/month).
Manual searches use more combos for broader coverage.
"""

import hashlib
import json
import os
import logging
from datetime import datetime, timedelta, date

import requests

from models.database import (
    get_active_config, create_search_run, finish_search_run,
    save_offer, add_log,
)

logger = logging.getLogger(__name__)

# ─── Confidence Ratings ──────────────────────────────────────────

AIRLINE_CONFIDENCE = {
    "LATAM": "Alto", "LATAM Airlines": "Alto",
    "Air France": "Alto",
    "KLM": "Alto", "KLM Royal Dutch Airlines": "Alto",
    "Lufthansa": "Alto",
    "British Airways": "Alto",
    "TAP": "Alto", "TAP Air Portugal": "Alto", "TAP Portugal": "Alto",
    "Iberia": "Alto",
    "ITA Airways": "Alto",
    "Swiss": "Alto", "SWISS": "Alto",
    "Emirates": "Alto",
    "Turkish Airlines": "Alto",
    "Ethiopian Airlines": "Médio",
    "Royal Air Maroc": "Médio",
    "Copa Airlines": "Médio",
    "Avianca": "Médio",
    "GOL": "Médio", "Gol": "Médio", "Gol Linhas Aéreas": "Médio",
    "Azul": "Médio", "Azul Brazilian Airlines": "Médio",
    "Condor": "Médio",
    "Norwegian": "Médio",
    "easyJet": "Baixo",
    "Ryanair": "Baixo",
}

SELLER_CONFIDENCE = {
    "Google Flights": "Alto",
    "Decolar": "Alto", "decolar.com": "Alto",
    "Kayak": "Alto", "Skyscanner": "Alto", "Momondo": "Alto",
    "Expedia": "Alto", "CVC": "Alto",
    "Kiwi.com": "Alto",
    "123milhas": "Baixo",
    "MaxMilhas": "Médio",
}

US_AIRPORT_CODES = {
    "ATL", "DFW", "DEN", "ORD", "LAX", "CLT", "MCO", "LAS",
    "PHX", "MIA", "SEA", "IAH", "JFK", "EWR", "SFO", "FLL",
    "MSP", "BOS", "DTW", "PHL", "LGA", "BWI", "SLC", "DCA",
    "IAD", "MDW", "TPA", "SAN", "HNL", "STL", "BNA", "AUS",
    "OAK", "MSY", "RDU", "SJC", "SMF", "CLE", "PIT", "CVG",
    "IND", "CMH", "MCI", "SAT", "SNA", "DAL", "HOU",
}


# ─── Helpers ─────────────────────────────────────────────────────

def generate_offer_hash(offer):
    key = (
        f"{offer['outbound_origin']}-{offer['outbound_destination']}-"
        f"{offer['outbound_date']}-{offer.get('outbound_time','')}-"
        f"{offer['inbound_origin']}-{offer['inbound_destination']}-"
        f"{offer['inbound_date']}-{offer.get('inbound_time','')}-"
        f"{offer.get('operating_airline','')}-{offer.get('seller','')}"
    )
    return hashlib.md5(key.encode()).hexdigest()[:16]


def has_us_connection(connections_str):
    if not connections_str:
        return False
    codes = [c.strip() for c in connections_str.split(",")]
    return any(code in US_AIRPORT_CODES for code in codes)


def get_confidence(airline, seller):
    airline_conf = AIRLINE_CONFIDENCE.get(airline, "Médio")
    seller_conf = SELLER_CONFIDENCE.get(seller, "Médio")
    levels = {"Alto": 3, "Médio": 2, "Baixo": 1}
    avg = (levels.get(airline_conf, 2) + levels.get(seller_conf, 2)) / 2
    if avg >= 2.5:
        return "Alto"
    elif avg >= 1.5:
        return "Médio"
    return "Baixo"


def generate_date_combinations(config, max_combos=None):
    """Generate date combinations respecting flexibility and ~14 day trip."""
    dep_date = date.fromisoformat(config["departure_date"])
    ret_date = date.fromisoformat(config["return_date"])
    flex = config.get("flexibility_days", 3)

    combos = []
    # Always include the base dates first
    combos.append((dep_date.isoformat(), ret_date.isoformat()))

    for d_offset in range(-flex, flex + 1):
        dep = dep_date + timedelta(days=d_offset)
        for r_offset in range(-flex, flex + 1):
            ret = ret_date + timedelta(days=r_offset)
            actual_trip = (ret - dep).days
            if 12 <= actual_trip <= 16:
                combo = (dep.isoformat(), ret.isoformat())
                if combo not in combos:
                    combos.append(combo)

    if max_combos:
        combos = combos[:max_combos]
    return combos


# ─── SerpAPI Google Flights Source ────────────────────────────────

class GoogleFlightsSource:
    """
    Searches Google Flights via SerpAPI.
    Free tier: 100 searches/month at https://serpapi.com
    """

    def __init__(self):
        self.api_key = os.environ.get("SERPAPI_KEY", "")
        self.calls_made = 0

    @property
    def available(self):
        return bool(self.api_key)

    def search_flights(self, config, dep_date, ret_date):
        """Search outbound and inbound flights and combine into offers."""
        origin_airports = [a.strip() for a in config["origin_airports"].split(",")]
        dest_airports = [a.strip() for a in config["destination_airports"].split(",")]
        ret_origins = [a.strip() for a in config["return_origin_airports"].split(",")]
        ret_dests = [a.strip() for a in config["return_destination_airports"].split(",")]
        passengers = config.get("passengers", 4)
        max_stops = config.get("max_stops", 1)

        # Use primary airports to minimize API calls
        # GRU is the main international airport in São Paulo
        primary_origin = origin_airports[0]  # GRU
        primary_dest = dest_airports[0]      # CDG
        primary_ret_origin = ret_origins[0]  # FCO
        primary_ret_dest = ret_dests[0] if ret_dests else primary_origin  # GRU

        # Search outbound: São Paulo → Paris
        outbound = self._search_oneway(
            primary_origin, primary_dest, dep_date,
            passengers, max_stops
        )
        add_log("DEBUG", f"Google Flights ida: {len(outbound)} resultados ({primary_origin}→{primary_dest} {dep_date})")

        # Search inbound: Roma → São Paulo
        inbound = self._search_oneway(
            primary_ret_origin, primary_ret_dest, ret_date,
            passengers, max_stops
        )
        add_log("DEBUG", f"Google Flights volta: {len(inbound)} resultados ({primary_ret_origin}→{primary_ret_dest} {ret_date})")

        # Combine outbound + inbound into complete offers
        offers = []
        for out in outbound:
            for inb in inbound:
                total_price = round(out["price"] + inb["price"], 2)
                offer = {
                    "price_total": total_price,
                    "price_per_person": round(total_price / passengers, 2),
                    "currency": "BRL",
                    "outbound_date": out["date"],
                    "outbound_time": out.get("time"),
                    "outbound_arrival_date": out.get("arrival_date"),
                    "outbound_arrival_time": out.get("arrival_time"),
                    "outbound_origin": out["origin"],
                    "outbound_destination": out["destination"],
                    "outbound_stops": out.get("stops", 0),
                    "outbound_connections": out.get("connections"),
                    "outbound_duration_minutes": out.get("duration"),
                    "outbound_airlines": out.get("airlines"),
                    "inbound_date": inb["date"],
                    "inbound_time": inb.get("time"),
                    "inbound_arrival_date": inb.get("arrival_date"),
                    "inbound_arrival_time": inb.get("arrival_time"),
                    "inbound_origin": inb["origin"],
                    "inbound_destination": inb["destination"],
                    "inbound_stops": inb.get("stops", 0),
                    "inbound_connections": inb.get("connections"),
                    "inbound_duration_minutes": inb.get("duration"),
                    "inbound_airlines": inb.get("airlines"),
                    "operating_airline": out.get("airlines", ""),
                    "seller": "Google Flights",
                    "booking_url": "",
                    "baggage_info": None,
                    "fare_rules": None,
                    "source": "Google Flights (SerpAPI)",
                }
                offer["confidence_level"] = get_confidence(
                    offer["operating_airline"], "Google Flights"
                )
                offer["offer_hash"] = generate_offer_hash(offer)
                offers.append(offer)

        return offers

    def _search_oneway(self, origin, destination, dep_date, passengers, max_stops):
        """Execute a single one-way search on Google Flights."""
        params = {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": dep_date,
            "type": "2",  # One way
            "adults": passengers,
            "travel_class": "1",  # Economy
            "currency": "BRL",
            "hl": "pt",
            "gl": "br",
            "api_key": self.api_key,
        }

        # Set stops filter
        if max_stops == 0:
            params["stops"] = "0"  # Non-stop only
        elif max_stops == 1:
            params["stops"] = "1"  # Up to 1 stop

        try:
            resp = requests.get(
                "https://serpapi.com/search",
                params=params, timeout=60,
            )
            self.calls_made += 1
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"SerpAPI request failed: {e}")
            return []

        # Check for API errors
        if "error" in data:
            logger.error(f"SerpAPI error: {data['error']}")
            return []

        results = []
        all_flights = data.get("best_flights", []) + data.get("other_flights", [])

        for flight_group in all_flights:
            flights = flight_group.get("flights", [])
            if not flights:
                continue

            stops = len(flights) - 1
            if stops > max_stops:
                continue

            # Extract connection airports
            connections = []
            for f in flights[:-1]:
                arr_id = f.get("arrival_airport", {}).get("id", "")
                connections.append(arr_id)

            conn_str = ",".join(connections)
            if has_us_connection(conn_str):
                continue

            first = flights[0]
            last = flights[-1]
            dep_airport = first.get("departure_airport", {})
            arr_airport = last.get("arrival_airport", {})

            # Airlines
            airlines_set = set()
            for f in flights:
                airline_name = f.get("airline", "")
                if airline_name:
                    airlines_set.add(airline_name)
            airlines = sorted(airlines_set)

            price = flight_group.get("price", 0)
            duration = flight_group.get("total_duration", 0)

            dep_time = dep_airport.get("time", "")
            arr_time = arr_airport.get("time", "")

            # Determine arrival date
            # Google Flights may show "+1" for next day arrivals
            arr_date_str = dep_date
            if last.get("arrival_airport", {}).get("time"):
                # If flight has overnight info, we can try to extract it
                overnight = flight_group.get("overnight", False)
                if overnight or (arr_time and dep_time and arr_time < dep_time and stops == 0):
                    dep_d = date.fromisoformat(dep_date)
                    arr_date_str = (dep_d + timedelta(days=1)).isoformat()

            results.append({
                "origin": dep_airport.get("id", origin),
                "destination": arr_airport.get("id", destination),
                "date": dep_date,
                "time": dep_time,
                "arrival_date": arr_date_str,
                "arrival_time": arr_time,
                "price": float(price) if price else 0,
                "stops": stops,
                "connections": conn_str if connections else None,
                "duration": duration,
                "airlines": ",".join(airlines),
            })

        return results


# ─── Main Agent Runner ───────────────────────────────────────────

def run_search(is_manual=False):
    """
    Execute the full flight search pipeline.

    Args:
        is_manual: If True, searches more date combos (manual trigger).
                   If False, uses fewer combos to conserve API calls (daily auto).
    """
    add_log("INFO", "Iniciando busca de voos...")
    config = get_active_config()
    if not config:
        add_log("ERROR", "Nenhuma configuração de busca ativa encontrada.")
        return

    run_id = create_search_run(config["id"])
    all_offers = []
    sources_used = []
    errors = []

    source = GoogleFlightsSource()

    if not source.available:
        add_log("WARNING",
                "SERPAPI_KEY não configurada. Configure a variável de ambiente "
                "com sua chave do SerpAPI (https://serpapi.com).")
        finish_search_run(run_id, "error", 0, "", "SERPAPI_KEY não configurada")
        return 0

    # Generate date combinations
    # Daily auto: 2 combos (4 API calls) to conserve quota
    # Manual: up to 5 combos (10 API calls) for broader coverage
    max_combos = 5 if is_manual else 2
    date_combos = generate_date_combinations(config, max_combos=max_combos)

    add_log("INFO", f"Buscando {len(date_combos)} combinação(ões) de datas "
            f"({'busca manual' if is_manual else 'busca automática'})")

    for dep_date, ret_date in date_combos:
        try:
            offers = source.search_flights(config, dep_date, ret_date)
            all_offers.extend(offers)
            if "Google Flights" not in sources_used:
                sources_used.append("Google Flights")
            add_log("INFO",
                    f"Google Flights: {len(offers)} ofertas para "
                    f"{dep_date} / {ret_date}")
        except Exception as e:
            err = f"Erro na busca ({dep_date}/{ret_date}): {str(e)}"
            errors.append(err)
            add_log("ERROR", err)

    add_log("INFO", f"Total de chamadas à API: {source.calls_made}")

    # Deduplicate
    seen = set()
    unique_offers = []
    for offer in all_offers:
        h = offer["offer_hash"]
        if h not in seen:
            seen.add(h)
            unique_offers.append(offer)

    # Sort by price
    unique_offers.sort(key=lambda x: x["price_total"])

    # Assign badges
    if unique_offers:
        unique_offers[0].setdefault("badges", []).append("Mais Barata")

        def cost_benefit_score(o):
            conf_score = {"Alto": 1, "Médio": 2, "Baixo": 3}.get(
                o.get("confidence_level", "Médio"), 2
            )
            dur = (
                (o.get("outbound_duration_minutes") or 999)
                + (o.get("inbound_duration_minutes") or 999)
            )
            return o["price_total"] * conf_score * (dur / 600)

        best_cb = min(unique_offers, key=cost_benefit_score)
        best_cb.setdefault("badges", []).append("Melhor Custo-Benefício")

        def total_duration(o):
            return (
                (o.get("outbound_duration_minutes") or 9999)
                + (o.get("inbound_duration_minutes") or 9999)
            )

        shortest = min(unique_offers, key=total_duration)
        shortest.setdefault("badges", []).append("Menor Tempo de Viagem")

        high_conf = [o for o in unique_offers if o.get("confidence_level") == "Alto"]
        if high_conf:
            high_conf[0].setdefault("badges", []).append("Mais Confiável")

    # Save all offers
    for offer in unique_offers:
        try:
            save_offer(run_id, offer)
        except Exception as e:
            add_log("ERROR", f"Erro ao salvar oferta: {e}")

    status = "completed" if unique_offers else "completed_empty"
    finish_search_run(
        run_id, status, len(unique_offers),
        ",".join(sources_used),
        "; ".join(errors) if errors else None,
    )
    add_log("INFO",
            f"Busca finalizada: {len(unique_offers)} ofertas únicas. "
            f"API calls: {source.calls_made}")
    return len(unique_offers)
