# Restore alerts from saved AI decisions; measurements never open an alert themselves.
from __future__ import annotations

import math


class FuelAlertTracker:
    ALERT_RESULTS = ("Monitor", "Unusual drop")

    # Accept only a usable saved comparison, not a fabricated value from an AI response.
    @staticmethod
    def valid_reference(reference, by_id: dict) -> bool:
        if not isinstance(reference, dict):
            return False
        ids = reference.get("entry_ids")
        if (not isinstance(ids, list) or len(ids) < 5
                or any(isinstance(entry_id, bool) or not isinstance(entry_id, int)
                       or entry_id not in by_id for entry_id in ids)
                or len(set(ids)) != len(ids)):
            return False
        for key in ("km_per_l", "distance_km", "litres"):
            value = reference.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                return False
        distance = sum(by_id[entry_id]["distance_km"] for entry_id in ids)
        litres = sum(by_id[entry_id]["litres_used"] for entry_id in ids)
        limits = reference.get("range")
        if (not isinstance(limits, list) or len(limits) != 2
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) for value in limits)):
            return False
        return (not isinstance(reference.get("count"), bool) and reference.get("count") == len(ids)
                and math.isclose(reference["distance_km"], distance)
                and math.isclose(reference["litres"], litres)
                and math.isclose(reference["km_per_l"], distance / litres)
                and math.isclose(limits[0], min(by_id[entry_id]["actual_km_per_l"] for entry_id in ids))
                and math.isclose(limits[1], max(by_id[entry_id]["actual_km_per_l"] for entry_id in ids)))

    # Reviews retain measurements while controlling which period future comparisons use.
    def restore(self, points: list[dict], reviews: list[dict], assessments: list[dict]) -> dict:
        by_id = {point["entry_id"]: point for point in points}
        reviewed = set()
        ordinary = set()
        excluded = set()
        epoch = 0
        recent_start = 0
        last_review = None
        for review in reviews:
            first = by_id.get(review.get("first_entry_id"))
            through = by_id.get(review.get("through_entry_id"))
            if first is None or through is None or first["position"] > through["position"]:
                continue
            period = points[first["position"]:through["position"] + 1]
            ids = {point["entry_id"] for point in period}
            reviewed.update(ids)
            decision = review["decision"]
            if decision == "ordinary_variation":
                ordinary.update(ids)
            elif decision == "confirmed_fault":
                excluded.update(ids)
                recent_start = max(recent_start, through["position"] + 1)
            elif decision == "changed_conditions":
                epoch = max(epoch, through["position"] + 1)
                recent_start = max(recent_start, epoch)
            last_review = review

        alert = None
        reference = None
        latest = None
        for assessment in assessments:
            through = by_id.get(assessment.get("assessed_through_entry_id"))
            if through is None or through["position"] < epoch:
                continue
            latest = assessment
            flagged = [by_id[entry_id] for entry_id in assessment.get("flagged_entry_ids", [])
                       if entry_id in by_id and entry_id not in reviewed
                       and by_id[entry_id]["position"] >= max(epoch, recent_start)]
            if assessment.get("anomaly_status") not in self.ALERT_RESULTS or not flagged:
                continue
            candidate = assessment.get("comparison_reference")
            if not self.valid_reference(candidate, by_id):
                continue
            first = min(flagged, key=lambda point: point["position"])
            if any(by_id[entry_id]["position"] >= first["position"] for entry_id in candidate["entry_ids"]):
                continue
            if alert is None:
                reference = candidate
                alert = {"first_entry_id": first["entry_id"], "first_date": first["date"],
                         "detected_entry_id": through["entry_id"],
                         "peak_status": assessment["anomaly_status"]}
            elif assessment["anomaly_status"] == "Unusual drop":
                alert["peak_status"] = "Unusual drop"
        if alert and points:
            alert["through_entry_id"] = points[-1]["entry_id"]
            alert["last_date"] = points[-1]["date"]
        return {"reviewed_entry_ids": sorted(reviewed), "ordinary_entry_ids": sorted(ordinary),
                "excluded_entry_ids": sorted(excluded), "epoch_start": epoch,
                "recent_start": recent_start, "alert": alert, "frozen_reference": reference,
                "last_review": last_review,
                "review_applied_now": bool(last_review and points
                                           and last_review["through_entry_id"] == points[-1]["entry_id"]),
                "latest_ai_assessment": latest,
                "latest_ai_status": latest["anomaly_status"] if latest else "Not assessed"}
