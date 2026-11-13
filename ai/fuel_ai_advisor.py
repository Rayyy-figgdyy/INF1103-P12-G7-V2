# Ask the existing AI providers to assess anomalies from calculated fuel evidence.
from __future__ import annotations

import json
import logging

logger = logging.getLogger("ai_manager")


class FuelAIAdvisor:
    ANOMALIES = ("Normal", "Monitor", "Unusual drop", "Unclear")
    TRENDS = ("Improving", "Stable", "Worsening", "Unclear")
    CONFIDENCE_LEVELS = ("Low", "Medium", "High")
    BASELINES = ("Suitable", "Uncertain", "Insufficient history")
    PATTERNS = ("Isolated", "Repeated", "Gradual", "No clear drop", "Insufficient history", "Unclear")

    # Reuse the same provider objects as the original maintenance feature.
    def __init__(self, providers: list):
        self.__providers = list(providers)

    # Check response structure and referenced records, without making an anomaly decision.
    @classmethod
    def validate_result(cls, answer, dashboard: dict | None = None) -> dict | None:
        if not isinstance(answer, dict):
            return None
        choices = {"anomaly_status": cls.ANOMALIES, "trend": cls.TRENDS,
                   "confidence": cls.CONFIDENCE_LEVELS, "baseline_assessment": cls.BASELINES,
                   "pattern": cls.PATTERNS}
        if any(answer.get(field) not in allowed for field, allowed in choices.items()):
            return None
        summary = answer.get("summary")
        if not isinstance(summary, str) or not 10 <= len(summary.strip()) <= 350:
            return None
        for field, minimum in (("possible_factors", 0), ("suggested_checks", 1)):
            items = answer.get(field)
            if not isinstance(items, list) or not minimum <= len(items) <= 2:
                return None
            if any(not isinstance(item, str) or not 3 <= len(item.strip()) <= 200 for item in items):
                return None
        ids = answer.get("flagged_entry_ids")
        if (not isinstance(ids, list) or len(ids) > 3
                or any(isinstance(entry_id, bool) or not isinstance(entry_id, int) or entry_id < 1
                       for entry_id in ids) or len(ids) != len(set(ids))):
            return None
        flagged = answer["anomaly_status"] in ("Monitor", "Unusual drop")
        if flagged != bool(ids):
            return None
        if dashboard is not None and any(entry_id not in dashboard.get("eligible_alert_entry_ids", [])
                                         for entry_id in ids):
            return None
        return {**{field: answer[field] for field in choices}, "summary": summary.strip(),
                "flagged_entry_ids": list(ids),
                "possible_factors": [item.strip() for item in answer["possible_factors"]],
                "suggested_checks": [item.strip() for item in answer["suggested_checks"]]}

    # Reject malformed JSON before its fields reach the logic manager.
    @classmethod
    def validate_response(cls, reply: str | None, dashboard: dict | None = None) -> dict | None:
        if not isinstance(reply, str) or not reply.strip():
            return None
        text = reply.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                text = "\n".join(lines[1:-1])
        try:
            return cls.validate_result(json.loads(text), dashboard)
        except (TypeError, ValueError):
            return None

