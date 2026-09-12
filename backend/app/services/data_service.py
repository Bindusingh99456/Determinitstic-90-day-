"""
Data Management & Decision Repository Service
Maintains user profiles, financial event streams, and purchase request decision history.
"""

from typing import Optional, List, Dict, Any
from app.data.loader import DataLoader
from app.models.financial import UserFinancialProfile, FinancialEvent, FinancialState
from app.utils.logger import logger


class DataService:
    """Orchestrates reading profiles, accounts, transactions, and request history."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DataService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, loader: Optional[DataLoader] = None):
        if self._initialized:
            return
        self.loader = loader or DataLoader()
        self._decision_history: Dict[str, Dict[str, Any]] = {}
        self._user_profiles: Dict[str, UserFinancialProfile] = {}
        self._user_events: Dict[str, List[FinancialEvent]] = {}
        self._request_counter: int = 1
        self._initialized = True

    def generate_next_request_id(self) -> str:
        """Generates sequential request ID e.g. R001, R002."""
        req_id = f"R{self._request_counter:03d}"
        self._request_counter += 1
        return req_id

    def save_decision(self, request_id: str, decision_payload: Dict[str, Any]) -> None:
        """Stores decision payload in request history."""
        self._decision_history[request_id] = decision_payload
        logger.info(f"Saved decision history for {request_id}")

    def get_decision(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves single decision by request_id."""
        return self._decision_history.get(request_id)

    def get_all_decisions(self) -> List[Dict[str, Any]]:
        """Retrieves list of all decision records in history."""
        return list(self._decision_history.values())

    def get_user_profile(self, user_id: str) -> Optional[UserFinancialProfile]:
        """Retrieves user profile by ID or creates default mock profile."""
        if user_id in self._user_profiles:
            return self._user_profiles[user_id]

        profile = self.loader.get_user_profile(user_id)
        if profile:
            self._user_profiles[user_id] = profile
            return profile

        return None

    def get_user_events(self, user_id: str) -> List[FinancialEvent]:
        """Retrieves financial events for a user."""
        if user_id in self._user_events:
            return self._user_events[user_id]

        events = self.loader.get_financial_events(user_id)
        if events:
            self._user_events[user_id] = events
            return events

        return []
