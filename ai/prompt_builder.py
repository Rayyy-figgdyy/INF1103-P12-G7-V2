"""
AI pipeline step 1: build the prompt for one check.
"""
from __future__ import annotations

import json

from ai.manual_reader import ManualReader


class PromptBuilder:
    """Step 1: turns one check record (a dict) into the AI prompt text."""

    @staticmethod
    def has_brake_history(record: dict) -> bool:
        """True when a Brake Pads check carries 3+ eligible history entries.
        Then the prompt adds the history and the reply must include history_pattern."""
        history = record.get("brake_pad_history")
        return (record.get("part_name") == "Brake Pads"
                and isinstance(history, list) and len(history) >= 3)

    def build(self, record: dict) -> str:
        """Build one AI prompt using the manual baseline and any eligible brake history."""
        part_words = ManualReader.PART_SEARCH_WORDS.get(record.get('part_name'),
                                                        [str(record.get('part_name'))])
        # The fixed urgency scale lines up with the thresholds in LogicManager.route.
        prompt = (
            "You are an automotive maintenance advisor in Singapore. The owner's "
            "manual for this car is attached. Use the manual as the authoritative "
            "maintenance baseline and assess how urgently one part needs servicing.\n\n"
            "VEHICLE\n"
            f"- Model: {record.get('car_model')}\n"
            f"- Condition when bought: {record.get('car_condition')}\n"
            f"- COE expiry date: {record.get('coe_expiry_date')}\n\n"
            "PART\n"
            f"- Part: {record.get('part_name')}\n"
            f"- The manual may call it: "
            f"{', '.join(part_words)}\n"
            "- For Tyres, the service interval means the tyre ROTATION interval; "
            "also consider the manual's tread-wear and inspection advice.\n"
            f"- Our stored schedule (from the manual's normal schedule; 0 = the manual gives "
            f"no limit of that kind): {record.get('action', 'replace')} every "
            f"{record.get('interval_km')} km or {record.get('interval_months')} months, "
            f"whichever comes first"
            f"{' (first change of this part)' if record.get('interval_stage') == 'first' else ''}"
            f"{' (interval after the first change)' if record.get('interval_stage') == 'repeat' else ''}\n"
            f"- Last serviced: {record.get('last_service_date')} at "
            f"{record.get('last_service_mileage')} km"
            f"{' (never replaced: counted from the car being new)' if record.get('last_service_mileage') == 0 and record.get('service_id') is None else ''}\n"
            f"- Today: {record.get('check_date')}, odometer {record.get('current_odometer')} km\n\n"
            "STEPS\n"
            "1. Find what the manual's NORMAL schedule says about this part: its replacement or "
            "inspection interval. For this project, use only the normal schedule. Do not use or "
            "mention severe-driving schedules, and do not infer a severe schedule from Singapore "
            "weather or traffic.\n"
            "2. Compare the distance AND time since the last service with that interval.\n"
            "3. Score urgency with this scale:\n"
            "   1-3  well within the interval (under 70% of distance and time used)\n"
            "   4-5  approaching the interval (70-100% used)\n"
            "   6-7  at or just past the interval, part not safety-critical\n"
            "   8-9  clearly overdue, or a safety-critical part (brake pads, "
            "tyres) at or past its interval\n"
            "   10   safety-critical and far overdue: do not drive until serviced\n"
            "   For a used car, the earlier service history is unknown, so lean "
            "one point higher when unsure.\n"
            "4. Set confidence:\n"
            "   High    the manual states an interval for this exact part and you used it\n"
            "   Medium  the manual only covers it indirectly (e.g. 'inspect' not "
            "'replace'), or disagrees with our stored normal schedule\n"
            "   Low     the manual does not cover this part; you used general knowledge\n\n"
        )

        with_history = self.has_brake_history(record)
        if with_history:
            history = record.get("brake_pad_history")
            prompt += (
                "PERSONALISED BRAKE-PAD HISTORY\n"
                # Provide every eligible history entry, including inspections.
                f"- Raw brake-pad servicing records: {json.dumps(history, ensure_ascii=False)}\n"
                "- These records passed the history eligibility checks. Consider all entries, "
                "but count ONLY service_action=replace as confirmed replacements.\n"
                "- Inspections provide context but do not count as replacements or reset a "
                "replacement interval; unknown actions are not confirmed replacements.\n"
                "- Calculate the replacement-to-replacement mileage intervals yourself.\n"
                "- Use the manual baseline AND this car's replacement pattern together to create "
                "ONE combined urgency_score. Do not create a separate history urgency score.\n"
                "- The manual remains authoritative. The history may add personalised context, "
                "but it must never be used to delay or ignore a manufacturer-required inspection "
                "or service.\n"
                "- Do not infer driving style, brake-pad thickness, or guaranteed remaining life.\n\n"
            )

        prompt += (
            "Reply with ONLY one JSON object with these required keys:\n"
            "{\n"
            '  "urgency_score": <integer 1-10>,\n'
            '  "confidence": <"High", "Medium" or "Low">,\n'
            '  "overdue_summary": <one short sentence such as "Engine oil: 650 km overdue" '
            'or "Tyres: 12 days overdue" or "Air filter: 3,000 km remaining">,\n'
            '  "recommended_action": <one short sentence telling the owner what to do next>,\n'
            '  "manual_reference": <where in the manual you found this, e.g. '
            '"Maintenance schedule, p. 7", or "Not covered in manual">'
        )
        if with_history:
            prompt += ',\n  "history_pattern": <one short sentence describing the calculated replacement intervals>'
        prompt += "\n}"
        return prompt
