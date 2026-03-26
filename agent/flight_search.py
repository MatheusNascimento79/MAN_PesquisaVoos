"""
Flight Search Agent - searches multiple sources for flight offers.

Supported sources:
1. Amadeus API (primary) - Official airline data
2. SerpAPI Google Flights (secondary) - Google Flights scraping
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

# Airline confidence ratings
AIRLINE_CONFIDENCE = {
    "LATAM": "Alto", "LA": "Alto", "JJ": "Alto",
    "Air France": "Alto", "AF": "Alto",
    "KLM": "Alto", "KL": "Alto",
    "Lufthansa": "Alto", "LH": "Alto",
    "British Airways": "Alto", "BA": "Alto",
    "TAP": "Alto", "TP": "Alto",
    "Iberia": "Alto", "IB": "Alto",
    "Alitalia": "Alto", "AZ": "Alto",
    "ITA Airways": "Alto",
    "Swiss": "Alto", "LX": "Alto",
    "Emirates": "Alto", "EK": "Alto",
    "Turkish Airlines": "Alto", "TK": "Alto",
    "Ethiopian Airlines": "Médio", "ET": "Médio",
    "Royal Air Maroc": "Médio", "AT": "Médio",
    "Copa Airlines": "Médio", "CM": "Médio",
    "Avianca": "Médio", "AV": "Médio",
    "GOL": "Médio", "G3": "Médio",
    "Azul": "Médio", "AD": "Médio",
}

SELLER_CONFIDENCE = {
    "airline_direct": "Alto",
    "Decolar": "Alto", "decolar.com": "Alto",
    "Kayak": "Alto", "Google Flights": "Alto",
    "Skyscanner": "Alto", "Momondo": "Alto",
    "Expedia": "Alto", "CVC": "Alto",
    "123milhas": "Baixo",
    "MaxMilhas": "Médio", "Submarino Viagens": "Médio",
}

US_AIRPORT_CODES = {
    "ATL", "DFW", "DEN", "ORD", "LAX", "CLT", "MCO", "LAS",
    "PHX", "MIA", "SEA", "IAH", "JFK", "EWR", "SFO", "FLL",
    "MSP", "BOS", "DTW", "PHL", "LGA", "BWI", "SLC", "DCA",
    "IAD", "MDW", "TPA", "SAN", "HNL", "STL", "BNA", "AUS",
    "OAK", "MSY", "RDU", "SJC", "SMF", "CLE", "PIT", "CVG",
    "IND", "CMH", "MCI", "SAT", "SNA", "DAL", "HOU",
}


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


def generate_date_combinations(config):
    dep_date = date.fromisoformat(config["departure_date"])
    ret_date = date.fromisoformat(config["return_date"])
    flex = config.get("flexibility_days", 3)
    trip_days = (ret_date - dep_date).days

    combos = []
    for d_offset in range(-flex, flex + 1):
        dep = dep_date + timedelta(days=d_offset)
        for r_offset in range(-flex, flex + 1):
            ret = ret_date + timedelta(days=r_offset)
            actual_trip = (ret - dep).days
            if 12 <= actual_trip <= 16:
                combos.append((dep.isoformat(), ret.isoformat()))
    return combos


# ─── Amadeus Source ───────────────────────────────────────────────

class AmadeusSource:
    def __init__(self):
        self.client_id = os.environ.get("AMADEUS_CLIENT_ID", "")
        self.client_secret = os.environ.get("AMADEUS_CLIENT_SECRET", "")
        self.token = None
        self.base_url = "https://test.api.amadeus.com"  # Use production when ready

    @property
    def available(self):
        return bool(self.client_id and self.client_secret)

    def authenticate(self):
        resp = requests.post(
            f"{self.base_url}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        self.token = resp.json()["access_token"]

    def search_flights(self, config, dep_date, ret_date):
        if not self.token:
            self.authenticate()

        origin_airports = [a.strip() for a in config["origin_airports"].split(",")]
        dest_airports = [a.strip() for a in config["destination_airports"].split(",")]
        ret_origins = [a.strip() for a in config["return_origin_airports"].split(",")]
        ret_dests = [a.strip() for a in config["return_destination_airports"].split(",")]
        passengers = config.get("passengers", 4)

        offers = []

        for orig in origin_airports:
            for dest in dest_airports:
                for ret_orig in ret_origins:
                    for ret_dest in ret_dests:
                        try:
                            results = self._search_pair(
                                orig, dest, ret_orig, ret_dest,
                                dep_date, ret_date, passengers, config
                            )
                            offers.extend(results)
                        except Exception as e:
                            logger.warning(
                                f"Amadeus search {orig}->{dest}, {ret_orig}->{ret_dest}: {e}"
                            )
        return offers

    def _search_pair(self, orig, dest, ret_orig, ret_dest, dep_date, ret_date,
                     passengers, config):
        headers = {"Authorization": f"Bearer {self.token}"}

        # Build multi-city search with flight-offers
        # Amadeus doesn't directly support multi-city in the simple endpoint,
        # so we search outbound and inbound separately and combine
        outbound_offers = self._search_oneway(
            orig, dest, dep_date, passengers, config, headers
        )
        inbound_offers = self._search_oneway(
            ret_orig, ret_dest, ret_date, passengers, config, headers
        )

        combined = []
        for out in outbound_offers:
            for inb in inbound_offers:
                offer = {
                    "price_total": round(out["price"] + inb["price"], 2),
                    "price_per_person": round(
                        (out["price"] + inb["price"]) / passengers, 2
                    ),
                    "currency": out.get("currency", "BRL"),
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
                    "seller": "Amadeus/Companhia Aérea",
                    "booking_url": "",
                    "baggage_info": out.get("baggage"),
                    "fare_rules": None,
                    "source": "Amadeus API",
                }
                offer["confidence_level"] = get_confidence(
                    offer["operating_airline"], "airline_direct"
                )
                offer["offer_hash"] = generate_offer_hash(offer)
                combined.append(offer)
        return combined

    def _search_oneway(self, origin, destination, dep_date, passengers, config, headers):
        params = {
            "originLocationCode": origin,
            "destinationLocationCode": destination,
            "departureDate": dep_date,
            "adults": passengers,
            "travelClass": config.get("cabin_class", "ECONOMY"),
            "nonStop": "false",
            "max": 15,
            "currencyCode": "BRL",
        }

        resp = requests.get(
            f"{self.base_url}/v2/shopping/flight-offers",
            headers=headers, params=params, timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for flight in data.get("data", []):
            for itinerary in flight.get("itineraries", []):
                segments = itinerary.get("segments", [])
                if not segments:
                    continue

                stops = len(segments) - 1
                if stops > config.get("max_stops", 1):
                    continue

                connections = []
                for seg in segments[:-1]:
                    arr_code = seg.get("arrival", {}).get("iataCode", "")
                    connections.append(arr_code)

                conn_str = ",".join(connections)
                if has_us_connection(conn_str):
                    continue

                first_seg = segments[0]
                last_seg = segments[-1]
                dep_info = first_seg.get("departure", {})
                arr_info = last_seg.get("arrival", {})

                dep_dt = dep_info.get("at", "")
                arr_dt = arr_info.get("at", "")

                duration_str = itinerary.get("duration", "")
                duration_min = parse_duration(duration_str)

                airlines = list({
                    seg.get("operating", {}).get("carrierCode", "")
                    or seg.get("carrierCode", "")
                    for seg in segments
                })
                airlines = [a for a in airlines if a]

                price_data = flight.get("price", {})
                price = float(price_data.get("grandTotal", 0))

                baggage = None
                traveler_pricings = flight.get("travelerPricings", [])
                if traveler_pricings:
                    fare_details = traveler_pricings[0].get(
                        "fareDetailsBySegment", []
                    )
                    if fare_details:
                        bag_info = fare_details[0].get("includedCheckedBags", {})
                        if bag_info:
                            qty = bag_info.get("quantity", 0)
                            wt = bag_info.get("weight")
                            unit = bag_info.get("weightUnit", "KG")
                            if wt:
                                baggage = f"{qty}x {wt}{unit}"
                            elif qty:
                                baggage = f"{qty} mala(s) incluída(s)"

                results.append({
                    "origin": dep_info.get("iataCode", origin),
                    "destination": arr_info.get("iataCode", destination),
                    "date": dep_dt[:10] if dep_dt else dep_date,
                    "time": dep_dt[11:16] if len(dep_dt) > 11 else None,
                    "arrival_date": arr_dt[:10] if arr_dt else None,
                    "arrival_time": arr_dt[11:16] if len(arr_dt) > 11 else None,
                    "price": price,
                    "currency": price_data.get("currency", "BRL"),
                    "stops": stops,
                    "connections": conn_str if connections else None,
                    "duration": duration_min,
                    "airlines": ",".join(airlines),
                    "baggage": baggage,
                })
                break  # Only first itinerary per offer

        return results


# ─── SerpAPI Google Flights Source ────────────────────────────────

class SerpAPISource:
    def __init__(self):
        self.api_key = os.environ.get("SERPAPI_KEY", "")

    @property
    def available(self):
        return bool(self.api_key)

    def search_flights(self, config, dep_date, ret_date):
        origin_airports = [a.strip() for a in config["origin_airports"].split(",")]
        dest_airports = [a.strip() for a in config["destination_airports"].split(",")]
        ret_origins = [a.strip() for a in config["return_origin_airports"].split(",")]
        passengers = config.get("passengers", 4)
        offers = []

        # SerpAPI Google Flights uses main airport codes
        for orig in origin_airports[:1]:  # Limit to reduce API calls
            for dest in dest_airports[:1]:
                try:
                    outbound = self._search(orig, dest, dep_date, passengers, config)
                except Exception as e:
                    logger.warning(f"SerpAPI outbound {orig}->{dest}: {e}")
                    outbound = []

            for ret_orig in ret_origins[:1]:
                for ret_dest in origin_airports[:1]:
                    try:
                        inbound = self._search(
                            ret_orig, ret_dest, ret_date, passengers, config
                        )
                    except Exception as e:
                        logger.warning(f"SerpAPI inbound {ret_orig}->{ret_dest}: {e}")
                        inbound = []

                    for out in outbound:
                        for inb in inbound:
                            offer = {
                                "price_total": round(
                                    out["price"] + inb["price"], 2
                                ),
                                "price_per_person": round(
                                    (out["price"] + inb["price"]) / passengers, 2
                                ),
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
                                "booking_url": out.get("booking_url", ""),
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

    def _search(self, origin, destination, dep_date, passengers, config):
        params = {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": dep_date,
            "type": "2",  # One way
            "adults": passengers,
            "travel_class": "1",  # Economy
            "stops": "1",  # Up to 1 stop
            "currency": "BRL",
            "hl": "pt",
            "gl": "br",
            "api_key": self.api_key,
        }
        resp = requests.get(
            "https://serpapi.com/search", params=params, timeout=60
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for flight_group in data.get("best_flights", []) + data.get("other_flights", []):
            flights = flight_group.get("flights", [])
            if not flights:
                continue

            stops = len(flights) - 1
            if stops > config.get("max_stops", 1):
                continue

            connections = []
            for f in flights[:-1]:
                arr = f.get("arrival_airport", {}).get("id", "")
                connections.append(arr)

            conn_str = ",".join(connections)
            if has_us_connection(conn_str):
                continue

            first = flights[0]
            last = flights[-1]
            dep_airport = first.get("departure_airport", {})
            arr_airport = last.get("arrival_airport", {})

            airlines = list({f.get("airline", "") for f in flights})
            airlines = [a for a in airlines if a]

            price = flight_group.get("price", 0)
            duration = flight_group.get("total_duration", 0)

            dep_time_raw = dep_airport.get("time", "")
            arr_time_raw = arr_airport.get("time", "")

            results.append({
                "origin": dep_airport.get("id", origin),
                "destination": arr_airport.get("id", destination),
                "date": dep_date,
                "time": dep_time_raw,
                "arrival_date": dep_date,  # approximate
                "arrival_time": arr_time_raw,
                "price": float(price) if price else 0,
                "stops": stops,
                "connections": conn_str if connections else None,
                "duration": duration,
                "airlines": ",".join(airlines),
            })

        return results


# ─── Utilities ────────────────────────────────────────────────────

def parse_duration(iso_duration):
    """Parse ISO 8601 duration like PT12H30M to minutes."""
    if not iso_duration:
        return None
    total = 0
    iso_duration = iso_duration.replace("PT", "").replace("P", "")
    if "D" in iso_duration:
        parts = iso_duration.split("D")
        total += int(parts[0]) * 1440
        iso_duration = parts[1] if len(parts) > 1 else ""
    if "H" in iso_duration:
        parts = iso_duration.split("H")
        total += int(parts[0]) * 60
        iso_duration = parts[1] if len(parts) > 1 else ""
    if "M" in iso_duration:
        total += int(iso_duration.replace("M", ""))
    return total if total > 0 else None


# ─── Main Agent Runner ───────────────────────────────────────────

def run_search():
    """Execute the full flight search pipeline."""
    add_log("INFO", "Iniciando busca de voos...")
    config = get_active_config()
    if not config:
        add_log("ERROR", "Nenhuma configuração de busca ativa encontrada.")
        return

    run_id = create_search_run(config["id"])
    all_offers = []
    sources_used = []
    errors = []

    # Initialize sources
    amadeus = AmadeusSource()
    serpapi = SerpAPISource()

    # Generate date combinations
    date_combos = generate_date_combinations(config)
    if not date_combos:
        date_combos = [(config["departure_date"], config["return_date"])]

    add_log("INFO", f"Testando {len(date_combos)} combinações de datas")

    # Limit combos to avoid excessive API calls
    date_combos = date_combos[:10]

    for dep_date, ret_date in date_combos:
        # Amadeus
        if amadeus.available:
            try:
                offers = amadeus.search_flights(config, dep_date, ret_date)
                all_offers.extend(offers)
                if "Amadeus" not in sources_used:
                    sources_used.append("Amadeus")
                add_log("INFO", f"Amadeus: {len(offers)} ofertas para {dep_date}/{ret_date}")
            except Exception as e:
                err = f"Amadeus error ({dep_date}): {str(e)}"
                errors.append(err)
                add_log("ERROR", err)

        # SerpAPI
        if serpapi.available:
            try:
                offers = serpapi.search_flights(config, dep_date, ret_date)
                all_offers.extend(offers)
                if "SerpAPI" not in sources_used:
                    sources_used.append("SerpAPI")
                add_log("INFO", f"SerpAPI: {len(offers)} ofertas para {dep_date}/{ret_date}")
            except Exception as e:
                err = f"SerpAPI error ({dep_date}): {str(e)}"
                errors.append(err)
                add_log("ERROR", err)

    if not sources_used:
        add_log("WARNING",
                "Nenhuma fonte de dados configurada. Configure AMADEUS_CLIENT_ID/"
                "AMADEUS_CLIENT_SECRET ou SERPAPI_KEY nas variáveis de ambiente.")

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

        # Best cost-benefit (price / confidence / duration)
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

        # Shortest travel time
        def total_duration(o):
            return (
                (o.get("outbound_duration_minutes") or 9999)
                + (o.get("inbound_duration_minutes") or 9999)
            )

        shortest = min(unique_offers, key=total_duration)
        shortest.setdefault("badges", []).append("Menor Tempo de Viagem")

        # Most reliable
        high_conf = [o for o in unique_offers if o.get("confidence_level") == "Alto"]
        if high_conf:
            high_conf[0].setdefault("badges", []).append("Mais Confiável")

    # Save all offers
    for offer in unique_offers:
        try:
            save_offer(run_id, offer)
        except Exception as e:
            add_log("ERROR", f"Erro ao salvar oferta: {e}")

    status = "completed" if unique_offers or sources_used else "completed_empty"
    finish_search_run(
        run_id, status, len(unique_offers),
        ",".join(sources_used),
        "; ".join(errors) if errors else None,
    )
    add_log("INFO",
            f"Busca finalizada: {len(unique_offers)} ofertas únicas de "
            f"{len(sources_used)} fonte(s)")
    return len(unique_offers)
