"""Compatibility agents for production test flows."""

from typing import Any

from src.agents.base import BaseAgent


class CompatibilityAgent(BaseAgent):
    """Lightweight stage agent used for pipeline smoke and load flows."""

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Mark a stage complete and return context artifacts."""

        action = f"{self.name.upper()}_COMPLETE"
        await self.log_decision(action, f"Completed compatibility stage {self.name}", 0.99)
        return {
            "agent": self.name,
            "status": "completed",
            "context_keys": sorted(context.keys()),
            "artifact": context.get("artifact") or context.get("dataset_id") or context.get("model_id"),
        }
