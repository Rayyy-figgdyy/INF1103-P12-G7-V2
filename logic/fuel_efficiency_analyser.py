# Calculate fuel measurements; the AI response supplies the anomaly assessment.
from __future__ import annotations

from models.fuel_entry import FuelEntry


class FuelEfficiencyAnalyser:
    MONITOR_PERCENT = 15
    INVESTIGATE_PERCENT = 20
    MIN_BASELINE_READINGS = 5
    RECENT_COUNT = 3

    # Block incomplete histories before any report lookup or API request.
    @classmethod
    def check_analysis_history(cls, dashboard: dict) -> str | None:
        if dashboard.get("refuel_count", 0) == 0:
            return "No fuel records yet. Add full-tank refuels before requesting an AI report."
        if (dashboard.get("baseline_km_per_l") is None
                or dashboard.get("baseline_count", 0) < cls.MIN_BASELINE_READINGS):
            return ("Not enough valid fuel history for an AI report. Need five older intervals "
                    "and three recent intervals (normally 9 full refuel records). "
                    f"More completed full-to-full intervals needed: {dashboard.get('intervals_needed', 8)}.")
        recent_needed = max(0, cls.RECENT_COUNT - dashboard.get("recent_count", 0))
        if recent_needed:
            return ("Not enough recent fuel history for an AI report. "
                    f"Record {recent_needed} more consecutive full-to-full interval(s).")
        return None

    # Never estimate across a missing refuel or count the first fill's litres as consumption.
    @staticmethod
    def measure(entries: list[FuelEntry]) -> list[dict]:
        points = []
        previous = None
        segment = 0
        for number, entry in enumerate(sorted(entries, key=lambda item: item.odometer_km), 1):
            if previous is None or entry.segment_start:
                segment += 1
                previous = entry
                continue
            distance = entry.odometer_km - previous.odometer_km
            if distance > 0:
                points.append({"entry_id": entry.entry_id if entry.entry_id is not None else number,
                               "position": len(points), "segment": segment,
                               "date": entry.refuel_date, "odometer_km": entry.odometer_km,
                               "distance_km": distance, "litres_used": entry.litres,
                               "actual_km_per_l": distance / entry.litres})
            previous = entry
        for point in points:
            point["current_segment"] = point["segment"] == segment
        return points

    # Combining totals gives each measured litre its proper weight.
    @staticmethod
    def average(points: list[dict]) -> dict | None:
        if not points:
            return None
        distance = sum(point["distance_km"] for point in points)
        litres = sum(point["litres_used"] for point in points)
        return {"km_per_l": distance / litres, "distance_km": distance, "litres": litres,
                "count": len(points), "entry_ids": [point["entry_id"] for point in points],
                "range": [min(point["actual_km_per_l"] for point in points),
                          max(point["actual_km_per_l"] for point in points)]}

    # Return a measured percentage, without assigning a warning or anomaly label.
    @staticmethod
    def drop_percent(baseline: float, actual: float) -> float:
        return (baseline - actual) / baseline * 100

    # Summarise measurements using only saved AI alert state and explicit user reviews.
    @classmethod
    def summarise(cls, points: list[dict], refuel_count: int, state: dict | None = None) -> dict:
        state = state or {}
        excluded = set(state.get("excluded_entry_ids", []))
        reviewed = set(state.get("reviewed_entry_ids", []))
        epoch = state.get("epoch_start", 0)
        recent_start = max(epoch, state.get("recent_start", 0))
        recent = [point for point in points
                  if point["position"] >= recent_start and point["current_segment"]
                  and point["entry_id"] not in excluded][-cls.RECENT_COUNT:]
        first_recent = recent[0]["position"] if recent else len(points)
        older = [point for point in points[epoch:first_recent] if point["entry_id"] not in excluded]
        reference = state.get("frozen_reference")
        if reference is None and len(older) >= cls.MIN_BASELINE_READINGS:
            reference = cls.average(older)
        recent_average = cls.average(recent)
        checks = []
        if reference:
            for point in recent:
                checks.append({"entry_id": point["entry_id"], "date": point["date"],
                               "actual_km_per_l": round(point["actual_km_per_l"], 2),
                               "baseline_km_per_l": round(reference["km_per_l"], 2),
                               "drop_percent": round(cls.drop_percent(
                                   reference["km_per_l"], point["actual_km_per_l"]), 1)})
        chart = []
        distance_total = 0
        litres_total = 0.0
        for point in points:
            distance_total += point["distance_km"]
            litres_total += point["litres_used"]
            chart.append({**{key: value for key, value in point.items()
                             if key not in ("position", "segment", "current_segment")},
                          "actual_km_per_l": round(point["actual_km_per_l"], 2),
                          "running_average_km_per_l": round(distance_total / litres_total, 2)})
        result = {
            "chart_points": chart, "latest_km_per_l": chart[-1]["actual_km_per_l"] if chart else None,
            "overall_average_km_per_l": round(distance_total / litres_total, 2) if litres_total else None,
            "total_distance_km": distance_total, "total_litres_used": round(litres_total, 3),
            "interval_count": len(points), "refuel_count": refuel_count,
            "baseline_km_per_l": round(reference["km_per_l"], 2) if reference else None,
            "baseline_count": reference["count"] if reference else 0,
            "baseline_entry_ids": list(reference["entry_ids"]) if reference else [],
            "baseline_range_km_per_l": [round(value, 2) for value in reference["range"]] if reference else None,
            "comparison_reference": reference,
            "recent_average_km_per_l": round(recent_average["km_per_l"], 2) if recent_average else None,
            "recent_drop_percent": round(cls.drop_percent(reference["km_per_l"], recent_average["km_per_l"]), 1)
            if reference and recent_average else None,
            "recent_individual_checks": checks, "recent_count": len(recent),
            "eligible_alert_entry_ids": [point["entry_id"] for point in recent
                                         if point["entry_id"] not in reviewed],
            "intervals_needed": max(0, cls.MIN_BASELINE_READINGS - len(older))
            + max(0, cls.RECENT_COUNT - len(recent)),
            "minimum_baseline_readings": cls.MIN_BASELINE_READINGS, "recent_window_size": cls.RECENT_COUNT,
            "thresholds": {"monitor_percent": cls.MONITOR_PERCENT,
                           "investigate_percent": cls.INVESTIGATE_PERCENT},
            "excluded_fault_intervals": len(excluded),
            "reviewed_ordinary_intervals": len(state.get("ordinary_entry_ids", [])),
            "baseline_frozen": bool(state.get("alert")), "alert_active": bool(state.get("alert")),
            "alert": state.get("alert"), "last_review": state.get("last_review"),
            "review_applied_now": state.get("review_applied_now", False),
            "latest_status": state.get("latest_ai_status", "Not assessed"),
            "latest_ai_assessment": state.get("latest_ai_assessment"),
        }
        result["analysis_problem"] = cls.check_analysis_history(result)
        result["analysis_ready"] = result["analysis_problem"] is None
        return result

    # Direct callers can calculate numbers without inventing an AI assessment.
    def analyse(self, entries: list[FuelEntry], state: dict | None = None) -> dict:
        return self.summarise(self.measure(entries), len(entries), state)
