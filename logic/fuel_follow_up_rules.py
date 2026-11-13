# Route validated AI fields into follow-up advice without classifying numerical drops.
from __future__ import annotations


class FuelFollowUpRules:

    # The multi-condition inspection rule depends on the AI's assessment and confidence.
    def decide(self, dashboard: dict, ai_result: dict) -> dict:
        status = ai_result.get("anomaly_status")
        confidence = ai_result.get("confidence")
        pattern = ai_result.get("pattern")
        if ai_result.get("ai_status") != "ok":
            action = "NEEDS MANUAL REVIEW - AI could not complete this assessment"
        elif status == "Unclear":
            action = "ASSESSMENT UNCLEAR - Review records and continue monitoring"
        elif (status == "Unusual drop" and pattern in ("Repeated", "Gradual")
              and ai_result.get("trend") == "Worsening" and confidence == "High"
              and ai_result.get("baseline_assessment") == "Suitable"):
            action = "INSPECTION ADVISED - AI found supported deterioration; consult a qualified mechanic"
        elif status in ("Monitor", "Unusual drop"):
            action = ("MONITOR AND REVIEW - Review the open AI alert and check the next interval"
                      if dashboard.get("alert_active") else
                      "VERIFY FUEL RECORDS - Check the measurements and save the assessment")
        elif dashboard.get("alert_active"):
            action = "REVIEW OPEN ALERT - A previous AI alert remains open until reviewed"
        else:
            action = "NO NEW UNUSUAL DROP - Continue recording full-tank refuels"
        return {"fuel_outcome": action,
                "ai_anomaly_status": status if ai_result.get("ai_status") == "ok" else None,
                "ai_confidence": confidence if ai_result.get("ai_status") == "ok" else None,
                "ai_pattern": pattern if ai_result.get("ai_status") == "ok" else None,
                "baseline_frozen": dashboard.get("baseline_frozen", False),
                "alert_active": dashboard.get("alert_active", False),
                "alert": dashboard.get("alert")}
