"""Tests for GarminClient.get_fitness_profile() field parsing."""

from paceforge.garmin.client import GarminClient


class _FakeGarmin:
    """Minimal stand-in for the garminconnect.Garmin client."""

    def __init__(self, morning_readiness=None, hill_score=None):
        self._morning_readiness = morning_readiness
        self._hill_score = hill_score

    def get_stats(self, d):
        return {}

    def get_heart_rates(self, d):
        return {}

    def get_training_status(self, d):
        return {}

    def get_max_metrics(self, d):
        return []

    def get_morning_training_readiness(self, d):
        return self._morning_readiness

    def get_hrv_data(self, d):
        return {}

    def get_lactate_threshold(self, latest=True):
        return {}

    def get_endurance_score(self, d):
        return {}

    def get_hill_score(self, d):
        return self._hill_score

    def get_body_composition(self, d):
        return {}

    def get_body_battery(self, d):
        return []

    def get_sleep_data(self, d):
        return {}

    def get_stress_data(self, d):
        return {}

    def get_race_predictions(self):
        return {}

    def get_personal_record(self):
        return []

    def get_activities_by_date(self, start, end, activity_type):
        return []


def _client(**overrides) -> GarminClient:
    client = GarminClient(email="a@example.com", password="x")
    client._client = _FakeGarmin(**overrides)
    return client


class TestMorningReadiness:
    def test_uses_morning_reading_score(self):
        profile = _client(morning_readiness={"score": 72}).get_fitness_profile()
        assert profile.training_readiness == 72

    def test_none_when_no_morning_reading(self):
        profile = _client(morning_readiness=None).get_fitness_profile()
        assert profile.training_readiness is None


class TestHillScore:
    def test_overall_score_parsed(self):
        profile = _client(hill_score={"overallScore": 55}).get_fitness_profile()
        assert profile.hill_score == 55

    def test_falls_back_to_alternate_keys(self):
        profile = _client(hill_score={"hillScore": 61}).get_fitness_profile()
        assert profile.hill_score == 61

    def test_none_when_unavailable(self):
        profile = _client(hill_score=None).get_fitness_profile()
        assert profile.hill_score is None
