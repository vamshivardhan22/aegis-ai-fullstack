"""Custom Locust load shape for M5 production validation."""

from locust import LoadTestShape


class AegisProductionShape(LoadTestShape):
    """Ramp to 1000 users, sustain, then ramp down."""

    stages = [
        {"duration": 120, "users": 1000, "spawn_rate": 10},
        {"duration": 300, "users": 1000, "spawn_rate": 10},
        {"duration": 420, "users": 0, "spawn_rate": 20},
    ]

    def tick(self) -> tuple[int, float] | None:
        """Return the current user target for Locust."""

        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return stage["users"], stage["spawn_rate"]
        return None
