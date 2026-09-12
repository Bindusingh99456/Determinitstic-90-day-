"""
Evidence Service & Conflict Resolution Manager
Merges facts extracted from messages and images with structured dataset records.
Applies Conservative Solvency Principle to resolve data conflicts.
"""

from typing import List, Optional
from app.models.evidence import ExtractedFact
from app.models.financial import FinancialEvent, EventType, EventStatus
from app.utils.logger import logger


class EvidenceService:
    """Manages multi-modal facts and resolves conflicting evidence."""

    def merge_facts_with_events(
        self, base_events: List[FinancialEvent], extracted_facts: List[ExtractedFact]
    ) -> List[FinancialEvent]:
        """
        Merges AI-extracted facts into base event stream.
        1. Explicit cancellation/settlement/amendment has top priority.
        2. Fills null amounts or updates event values using Conservative Solvency Principle.
        3. Updates event dates or recurrence patterns if explicitly declared in evidence.
        4. Appends high-confidence standalone facts as new evidence events.
        """
        logger.info(f"Merging {len(extracted_facts)} extracted facts into {len(base_events)} base events")

        # Copy events to avoid mutating original references
        event_map = {e.event_id: e.model_copy(deep=True) for e in base_events}
        standalone_facts: List[ExtractedFact] = []

        for fact in extracted_facts:
            target_id = fact.event_id or fact.target_event_id

            if target_id and target_id in event_map:
                event = event_map[target_id]
                fact_type = (fact.fact_type or "").lower()

                # 1. Cancellations & Settlements
                if any(kw in fact_type for kw in ["cancel", "settlement", "waived", "refund"]):
                    event.status = EventStatus.CANCELLED
                    logger.debug(f"Event {target_id} marked CANCELLED via evidence fact {fact.fact_id}")

                # 2. Amount Amendments / Increases / Decreases
                val = fact.value if fact.value is not None else fact.amount
                if val is not None:
                    if event.event_type == EventType.EXPENSE:
                        # Conservative Solvency Principle: Choose higher expense value
                        if event.amount is None or val > event.amount or "increase" in fact_type or "amendment" in fact_type:
                            event.amount = val
                    elif event.event_type == EventType.INCOME:
                        # Conservative Solvency Principle: Choose lower income value
                        if event.amount is None or val < event.amount or "decrease" in fact_type:
                            event.amount = val

                # 3. Date Updates
                if fact.effective_date:
                    event.event_date = fact.effective_date

                # 4. Recurrence updates
                if fact.recurrence_pattern:
                    event.is_recurring = True
                    event.recurrence_pattern = fact.recurrence_pattern

            else:
                if fact.confidence >= 0.6 and (fact.value is not None or fact.amount is not None):
                    standalone_facts.append(fact)

        # Convert remaining high-confidence standalone facts into new events
        new_events: List[FinancialEvent] = []
        for sf in standalone_facts:
            fact_type = (sf.fact_type or "").lower()
            evt_type = EventType.INCOME if ("income" in fact_type or "bonus" in fact_type or "salary" in fact_type) else EventType.EXPENSE
            amt = sf.value if sf.value is not None else sf.amount

            new_evt = FinancialEvent(
                event_id=f"EVT_{sf.fact_id}",
                user_id=sf.source_id,
                account_id="ACC_EVIDENCE",
                event_type=evt_type,
                status=EventStatus.PENDING if sf.is_uncertain else EventStatus.CONFIRMED,
                amount=amt,
                currency=sf.currency or "USD",
                event_date=sf.effective_date or "2026-09-12",
                is_recurring=bool(sf.recurrence_pattern),
                recurrence_pattern=sf.recurrence_pattern,
                category="EVIDENCE_DISCOVERY",
                linked_event_id=sf.source_id,
            )
            new_events.append(new_evt)

        merged_result = list(event_map.values()) + new_events
        return merged_result
