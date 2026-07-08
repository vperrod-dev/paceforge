"""Tests for the VDOT pace calculator."""

from paceforge.engine.vdot import (
    paces_from_race,
    paces_from_vdot,
    vdot_from_race,
)


class TestVdotFromRace:
    def test_5k_in_20_min(self):
        """A 20:00 5K should produce a VDOT around 49-51."""
        vdot = vdot_from_race(5000, 20 * 60)
        assert 48 < vdot < 52

    def test_marathon_sub_3(self):
        """A sub-3 marathon (~2:59) should produce VDOT ~54-55."""
        vdot = vdot_from_race(42195, 2 * 3600 + 59 * 60)
        assert 53 < vdot < 57

    def test_10k_in_45_min(self):
        """A 45:00 10K → VDOT ~44-47."""
        vdot = vdot_from_race(10000, 45 * 60)
        assert 44 < vdot < 47

    def test_half_marathon_1h45(self):
        """A 1:45 half marathon → VDOT ~41-44."""
        vdot = vdot_from_race(21097.5, 105 * 60)
        assert 41 < vdot < 45


class TestPacesFromVdot:
    def test_vdot_50_easy_pace(self):
        """VDOT 50 easy pace should be ~290-319 sec/km (4:50-5:19/km)."""
        paces = paces_from_vdot(50)
        assert 280 < paces.easy_low < 300
        assert 310 < paces.easy_high < 330

    def test_vdot_50_interval_pace(self):
        """VDOT 50 interval pace should be ~243 sec/km (~4:03/km)."""
        paces = paces_from_vdot(50)
        assert 235 < paces.interval < 250

    def test_paces_decrease_with_higher_vdot(self):
        slow = paces_from_vdot(35)
        fast = paces_from_vdot(60)
        assert fast.easy_low < slow.easy_low
        assert fast.marathon < slow.marathon
        assert fast.interval < slow.interval

    def test_interpolation_between_table_entries(self):
        """VDOT 44.5 should interpolate between 44 and 45."""
        paces = paces_from_vdot(44.5)
        p44 = paces_from_vdot(44)
        p45 = paces_from_vdot(45)
        assert p45.easy_low <= paces.easy_low <= p44.easy_low

    def test_boundary_low(self):
        """VDOT below table minimum should clamp."""
        paces = paces_from_vdot(20)
        assert paces.easy_low > 0

    def test_boundary_high(self):
        """VDOT above table maximum should clamp."""
        paces = paces_from_vdot(90)
        assert paces.easy_low > 0

    def test_summary_formatting(self):
        paces = paces_from_vdot(50)
        summary = paces.summary()
        assert "Easy" in summary
        assert "/km" in summary["Easy"]


class TestPacesFromRace:
    def test_round_trip(self):
        """Generate paces from a 5K time and verify they are reasonable."""
        paces = paces_from_race(5000, 25 * 60)  # 25 min 5K
        assert paces.easy_low > 0
        assert paces.threshold < paces.easy_low
        assert paces.interval < paces.threshold


class TestPaceBands:
    def test_easy_band_is_table_range(self):
        paces = paces_from_vdot(50)
        assert paces.band("easy") == (paces.easy_low, paces.easy_high)

    def test_band_brackets_center(self):
        paces = paces_from_vdot(54.7)
        for key in ("marathon", "threshold", "interval", "repetition"):
            low, high = paces.band(key)
            center = getattr(paces, key)
            assert low < center < high

    def test_bands_wider_than_gps_noise(self):
        """Windows must exceed ~±3 s/km or the watch alerts constantly."""
        paces = paces_from_vdot(54.7)
        for key in ("marathon", "threshold", "interval", "repetition"):
            low, high = paces.band(key)
            assert high - low > 8, f"{key} band {high - low:.1f}s too narrow"

    def test_threshold_band_slow_side_biased(self):
        paces = paces_from_vdot(50)
        low, high = paces.band("threshold")
        assert high - paces.threshold > paces.threshold - low
