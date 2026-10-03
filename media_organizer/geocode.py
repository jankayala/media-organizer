"""Reverse geocoding: GPS coordinates in, ``("Berlin", "Germany")`` out."""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

from media_organizer import __version__
from media_organizer.cities import CITIES, City
from media_organizer.config import NOMINATIM_URL, GeocoderMode

EARTH_RADIUS_KM = 6371.0088
USER_AGENT = f"media-organizer/{__version__} (local media organizer)"
NOMINATIM_MIN_INTERVAL_SECONDS = 1.0


class LocationResolver(Protocol):
    """Anything that can turn coordinates into location tags."""

    name: str
    #: Problems worth reporting; the planner copies them into the summary.
    warnings: list[str]

    def resolve(self, latitude: float, longitude: float) -> tuple[str, ...]:
        """Return an ordered tuple of tags, empty when nothing is known."""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


class OfflineCityResolver:
    """Nearest city from a bundled table. No network, no caching on disk."""

    name = "offline"

    def __init__(self, max_distance_km: float = 50.0, cities: tuple[City, ...] = CITIES):
        self.max_distance_km = max_distance_km
        self.cities = cities
        self.warnings: list[str] = []
        self._cache: dict[tuple[int, int], tuple[str, ...]] = {}

    def resolve(self, latitude: float, longitude: float) -> tuple[str, ...]:
        key = (round(latitude, 3), round(longitude, 3))
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        best: tuple[float, City] | None = None
        for city in self.cities:
            distance = haversine_km(latitude, longitude, city.latitude, city.longitude)
            if best is None or distance < best[0]:
                best = (distance, city)

        result: tuple[str, ...] = ()
        if best is not None and best[0] <= self.max_distance_km:
            result = (best[1].name, best[1].country)
        self._cache[key] = result
        return result


class NominatimResolver:
    """OpenStreetMap lookups. Requires network access and honours its rate limit.

    A coordinate without an address yields no tags instead of a guess, and every
    failed request is recorded in :attr:`warnings`.
    """

    name = "nominatim"

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.warnings: list[str] = []
        self._cache: dict[tuple[int, int], tuple[str, ...]] = {}
        self._last_request = 0.0

    def resolve(self, latitude: float, longitude: float) -> tuple[str, ...]:
        key = (round(latitude, 3), round(longitude, 3))
        if key in self._cache:
            return self._cache[key]

        payload = self._fetch(latitude, longitude)
        result = self._tags_from_payload(payload) if payload else ()
        self._cache[key] = result
        return result

    def _fetch(self, latitude: float, longitude: float) -> dict | None:
        query = urllib.parse.urlencode(
            {
                "format": "jsonv2",
                "lat": f"{latitude:.6f}",
                "lon": f"{longitude:.6f}",
                "zoom": 10,
                "addressdetails": 1,
            }
        )
        request = urllib.request.Request(
            f"{NOMINATIM_URL}?{query}",
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
        )

        wait = NOMINATIM_MIN_INTERVAL_SECONDS - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            message = f"reverse geocoding failed for {latitude:.4f},{longitude:.4f}: {exc}"
            if message not in self.warnings:
                self.warnings.append(message)
            return None

    def _tags_from_payload(self, payload: dict) -> tuple[str, ...]:
        address = payload.get("address") or {}
        if not isinstance(address, dict):
            return ()

        city = _first_present(address, ("city", "town", "village", "municipality", "hamlet"))
        region = _first_present(address, ("state", "region", "province"))
        country = _first_present(address, ("country",))

        tags: list[str] = []
        for candidate in (city, region, country):
            if candidate and candidate not in tags:
                tags.append(candidate)

        # Drop the city tag when it merely repeats the region.
        if len(tags) == 2 and tags[0] == tags[1]:
            tags.pop(0)
        return tuple(tags)


class NullResolver:
    """Never produces tags; used by ``--geocoder none``."""

    name = "none"

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def resolve(self, latitude: float, longitude: float) -> tuple[str, ...]:
        return ()


def _first_present(mapping: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def build_resolver(mode: GeocoderMode, max_distance_km: float) -> LocationResolver:
    """Create the resolver for ``mode``; ``auto`` prefers the offline table.

    ``max_distance_km`` is the search radius of the offline table only.
    """
    if mode is GeocoderMode.NONE:
        return NullResolver()
    if mode is GeocoderMode.NOMINATIM:
        return NominatimResolver()
    return OfflineCityResolver(max_distance_km=max_distance_km)