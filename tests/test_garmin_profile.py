"""Tests for GarminClient.get_fitness_profile() field parsing."""

from paceforge.garmin.client import GarminClient


class _FakeGarmin:
    """Minimal stand-in for the garminconnect.Garmin client."""

    def __init__(self, morning_readiness=None, hill_score=None, respiration=None,
                 spo2=None, running_tolerance=None):
        self._morning_readiness = morning_readiness
        self._hill_score = hill_score
        self._respiration = respiration
        self._spo2 = spo2
        self._running_tolerance = running_tolerance

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

    def get_respiration_data(self, d):
        return self._respiration

    def get_spo2_data(self, d):
        return self._spo2

    def get_running_tolerance(self, start, end, aggregation="weekly"):
        return self._running_tolerance

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


class TestRespiration:
    def test_sleep_average_parsed(self):
        profile = _client(respiration={"avgSleepRespirationValue": 14.2}).get_fitness_profile()
        assert profile.respiration_avg_sleep == 14.2

    def test_falls_back_to_waking_average(self):
        profile = _client(respiration={"avgWakingRespirationValue": 16.0}).get_fitness_profile()
        assert profile.respiration_avg_sleep == 16.0

    def test_none_when_unavailable(self):
        profile = _client(respiration=None).get_fitness_profile()
        assert profile.respiration_avg_sleep is None


class TestSpo2:
    def test_average_parsed(self):
        profile = _client(spo2={"averageSpO2": 96}).get_fitness_profile()
        assert profile.spo2_avg == 96

    def test_none_when_unavailable(self):
        profile = _client(spo2=None).get_fitness_profile()
        assert profile.spo2_avg is None


class TestRunningTolerance:
    def test_latest_point_parsed(self):
        points = [{"tolerance": 42.0}, {"tolerance": 45.5}]
        profile = _client(running_tolerance=points).get_fitness_profile()
        assert profile.running_tolerance == 45.5

    def test_none_when_empty(self):
        profile = _client(running_tolerance=[]).get_fitness_profile()
        assert profile.running_tolerance is None


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
