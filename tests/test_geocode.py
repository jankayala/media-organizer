"""Tests for GPS reverse geocoding."""

from __future__ import annotations

import unittest

from media_organizer.config import GeocoderMode
from media_organizer.geocode import (
    NullResolver,
    OfflineCityResolver,
    build_resolver,
    haversine_km,
)


class HaversineTests(unittest.TestCase):
    def test_zero_distance(self) -> None:
        self.assertAlmostEqual(haversine_km(52.52, 13.405, 52.52, 13.405), 0.0, places=6)

    def test_known_distance(self) -> None:
        # Berlin -> Hamburg is roughly 255 km.
        self.assertAlmostEqual(
            haversine_km(52.5200, 13.4050, 53.5511, 9.9937), 255.0, delta=5.0
        )


class OfflineResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = OfflineCityResolver(max_distance_km=50.0)

    def test_resolves_berlin(self) -> None:
        self.assertEqual(self.resolver.resolve(52.5200, 13.4050), ("Berlin", "Germany"))

    def test_resolves_negative_coordinates(self) -> None:
        self.assertEqual(
            self.resolver.resolve(-33.8688, 151.2093), ("Sydney", "Australia")
        )

    def test_returns_nothing_beyond_the_radius(self) -> None:
        # Middle of the Atlantic.
        self.assertEqual(self.resolver.resolve(0.0, -30.0), ())

    def test_results_are_cached(self) -> None:
        first = self.resolver.resolve(48.1351, 11.5820)
        self.assertEqual(self.resolver.resolve(48.1351, 11.5820), first)
        self.assertEqual(len(self.resolver._cache), 1)


class ResolverFactoryTests(unittest.TestCase):
    def test_auto_and_offline_use_the_builtin_table(self) -> None:
        self.assertIsInstance(build_resolver(GeocoderMode.AUTO, 50.0), OfflineCityResolver)
        self.assertIsInstance(build_resolver(GeocoderMode.OFFLINE, 50.0), OfflineCityResolver)

    def test_none_returns_no_tags(self) -> None:
        resolver = build_resolver(GeocoderMode.NONE, 50.0)
        self.assertIsInstance(resolver, NullResolver)
        self.assertEqual(resolver.resolve(52.52, 13.405), ())


if __name__ == "__main__":
    unittest.main()