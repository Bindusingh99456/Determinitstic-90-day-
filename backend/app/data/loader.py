"""
Forensic CSV & JSON Data Loader
Loads dataset files, validates required columns, preserves missing values (never defaulting null to zero),
normalizes currencies, flags/deduplicates lifecycle events, and indexes relational links.
"""

import os
from typing import List, Dict, Any, Optional, Set
import pandas as pd
import numpy as np
from app.models.financial import (
    UserFinancialProfile,
    FinancialAccount,
    FinancialEvent,
    AccountType,
    EventType,
    EventStatus,
    ExchangeRate,
)
from app.models.requests import PurchaseRequest, PaymentOption, PaymentOptionType, SpendingCutback
from app.models.evidence import ChatMessage, ImageRecord, EvidenceType
from app.utils.logger import logger
from app.utils.date_helpers import parse_date


class DataValidationError(Exception):
    """Raised when CSV datasets fail structural or data-integrity validation."""
    pass


class DataLoader:
    """
    Reusable forensic data loading and normalization component.
    Loads and links:
    - user_id
    - request_id
    - event_id
    - linked_event_id
    - related_event_id
    - image_id
    - payment_option_id
    """

    DEFAULT_EXCHANGE_RATES: Dict[str, float] = {
        "USD": 1.0,
        "EUR": 1.08,
        "GBP": 1.27,
        "CAD": 0.74,
        "JPY": 0.0067,
        "AUD": 0.65,
    }

    def __init__(self, dataset_dir: str = "dataset"):
        self.dataset_dir = dataset_dir
        self.user_profiles: Dict[str, UserFinancialProfile] = {}
        self.financial_events: Dict[str, List[FinancialEvent]] = {}  # user_id -> List[FinancialEvent]
        self.requests: Dict[str, List[PurchaseRequest]] = {}        # user_id -> List[PurchaseRequest]
        self.payment_options: Dict[str, List[PaymentOption]] = {}  # request_id -> List[PaymentOption]
        self.messages: Dict[str, List[ChatMessage]] = {}           # user_id -> List[ChatMessage]
        self.images: Dict[str, List[ImageRecord]] = {}             # user_id -> List[ImageRecord]
        self.exchange_rates: Dict[str, float] = dict(self.DEFAULT_EXCHANGE_RATES)

    # --- Exchange Rate Access & Normalization ---
    def load_exchange_rates_from_df(self, df: pd.DataFrame) -> None:
        """Loads exchange rates from a DataFrame with columns [from_currency, rate]."""
        self.validate_columns(df, ["from_currency", "rate"], "exchange_rates")
        for _, row in df.iterrows():
            from_curr = str(row["from_currency"]).upper().strip()
            rate = float(row["rate"])
            if rate <= 0:
                raise DataValidationError(f"Invalid non-positive exchange rate for {from_curr}: {rate}")
            self.exchange_rates[from_curr] = rate

    def get_exchange_rate(self, from_currency: str, to_currency: str = "USD") -> float:
        from_curr = from_currency.upper().strip()
        to_curr = to_currency.upper().strip()

        if from_curr == to_curr:
            return 1.0

        if from_curr in self.exchange_rates and to_curr == "USD":
            return self.exchange_rates[from_curr]

        raise DataValidationError(f"No exchange rate mapping found from {from_currency} to {to_currency}")

    def normalize_amount_to_usd(self, amount: Optional[float], currency: str) -> Optional[float]:
        """Converts amount to USD while strictly preserving None/NaN."""
        if amount is None or pd.isna(amount):
            return None
        rate = self.get_exchange_rate(currency, "USD")
        return round(float(amount) * rate, 2)

    # --- Validation Utilities ---
    @staticmethod
    def validate_columns(df: pd.DataFrame, required_cols: List[str], dataset_name: str) -> None:
        """Validates that all required columns exist in DataFrame."""
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            raise DataValidationError(
                f"Dataset '{dataset_name}' is missing required column(s): {', '.join(missing)}"
            )

    @staticmethod
    def safe_parse_float(val: Any, field_name: str, allow_none: bool = True) -> Optional[float]:
        """Parses a float value safely. NEVER converts NaN/null to 0.0 if allow_none is True."""
        if pd.isna(val) or val is None or str(val).strip() == "" or str(val).strip().lower() == "nan":
            if allow_none:
                return None
            raise DataValidationError(f"Field '{field_name}' cannot be empty or null.")
        try:
            return float(val)
        except (ValueError, TypeError):
            raise DataValidationError(f"Field '{field_name}' must be a valid number, got: {val}")

    # --- User Profiles Loader ---
    def load_user_profiles_from_df(self, accounts_df: pd.DataFrame) -> None:
        """Loads user profiles and financial accounts from a DataFrame."""
        self.validate_columns(accounts_df, ["user_id", "account_id", "type", "current_balance"], "accounts")

        for _, row in accounts_df.iterrows():
            user_id = str(row["user_id"]).strip()
            account_id = str(row["account_id"]).strip()
            acc_type_str = str(row["type"]).strip().upper()

            try:
                acc_type = AccountType(acc_type_str)
            except ValueError:
                raise DataValidationError(f"Invalid account type '{acc_type_str}' for account {account_id}")

            balance = self.safe_parse_float(row["current_balance"], "current_balance", allow_none=False)
            curr = str(row.get("currency", "USD")).strip().upper() or "USD"
            limit = self.safe_parse_float(row.get("credit_limit"), "credit_limit")
            min_pay = self.safe_parse_float(row.get("minimum_payment_due"), "minimum_payment_due")
            buffer = self.safe_parse_float(row.get("minimum_safety_buffer"), "minimum_safety_buffer") or 1000.0

            account = FinancialAccount(
                account_id=account_id,
                type=acc_type,
                currency=curr,
                current_balance=balance,
                credit_limit=limit,
                minimum_payment_due=min_pay,
            )

            if user_id not in self.user_profiles:
                self.user_profiles[user_id] = UserFinancialProfile(
                    user_id=user_id,
                    accounts=[account],
                    minimum_safety_buffer=buffer,
                    base_currency="USD",
                )
            else:
                self.user_profiles[user_id].accounts.append(account)

    # --- Financial Events Loader ---
    def load_financial_events_from_df(self, events_df: pd.DataFrame) -> List[FinancialEvent]:
        """
        Loads financial events, preserves missing amounts, normalizes currency to USD,
        and resolves lifecycle updates via related_event_id.
        """
        self.validate_columns(
            events_df,
            ["event_id", "user_id", "account_id", "event_type", "status", "event_date", "category"],
            "financial_events",
        )

        parsed_events: List[FinancialEvent] = []

        for _, row in events_df.iterrows():
            event_id = str(row["event_id"]).strip()
            user_id = str(row["user_id"]).strip()
            account_id = str(row["account_id"]).strip()
            event_type_str = str(row["event_type"]).strip().upper()
            status_str = str(row["status"]).strip().upper()
            date_str = str(row["event_date"]).strip()
            category = str(row["category"]).strip()

            # Date parsing validation
            try:
                parse_date(date_str)
            except Exception:
                raise DataValidationError(f"Invalid date format for event {event_id}: '{date_str}'")

            try:
                event_type = EventType(event_type_str)
            except ValueError:
                raise DataValidationError(f"Invalid event_type '{event_type_str}' for event {event_id}")

            try:
                status = EventStatus(status_str)
            except ValueError:
                raise DataValidationError(f"Invalid status '{status_str}' for event {event_id}")

            # Missing amount handling: strictly preserve None if NaN/null
            raw_amount = row.get("amount")
            amount = self.safe_parse_float(raw_amount, "amount", allow_none=True)
            currency = str(row.get("currency", "USD")).strip().upper() or "USD"

            # Normalize amount to USD if present
            usd_amount = self.normalize_amount_to_usd(amount, currency) if amount is not None else None

            is_recurring = bool(row.get("is_recurring", False))
            rec_pattern = str(row.get("recurrence_pattern")).strip() if pd.notna(row.get("recurrence_pattern")) else None
            merchant = str(row.get("merchant")).strip() if pd.notna(row.get("merchant")) else None
            related_id = str(row.get("related_event_id")).strip() if pd.notna(row.get("related_event_id")) and str(row.get("related_event_id")).strip() != "" else None
            linked_id = str(row.get("linked_event_id")).strip() if pd.notna(row.get("linked_event_id")) and str(row.get("linked_event_id")).strip() != "" else None

            event = FinancialEvent(
                event_id=event_id,
                user_id=user_id,
                account_id=account_id,
                event_type=event_type,
                status=status,
                amount=usd_amount,
                currency="USD",
                event_date=date_str,
                is_recurring=is_recurring,
                recurrence_pattern=rec_pattern,
                category=category,
                merchant=merchant,
                related_event_id=related_id,
                linked_event_id=linked_id,
            )
            parsed_events.append(event)

        # Deduplicate and resolve lifecycle transitions via related_event_id
        resolved_events = self._resolve_lifecycle_events(parsed_events)

        # Index by user_id
        for evt in resolved_events:
            if evt.user_id not in self.financial_events:
                self.financial_events[evt.user_id] = []
            self.financial_events[evt.user_id].append(evt)

        return resolved_events

    def _resolve_lifecycle_events(self, events: List[FinancialEvent]) -> List[FinancialEvent]:
        """
        Lifecycle resolution:
        If event B has related_event_id = event A.event_id and status is CONFIRMED,
        event A is superseded by event B and marked EventStatus.SUPERSEDED.
        """
        event_map = {e.event_id: e for e in events}
        superseded_ids: Set[str] = set()

        for evt in events:
            if evt.related_event_id and evt.related_event_id in event_map:
                parent = event_map[evt.related_event_id]
                if evt.status == EventStatus.CONFIRMED:
                    superseded_ids.add(parent.event_id)

        result: List[FinancialEvent] = []
        for evt in events:
            if evt.event_id in superseded_ids:
                updated_evt = evt.model_copy(update={"status": EventStatus.SUPERSEDED})
                result.append(updated_evt)
            else:
                result.append(evt)

        return result

    # --- Purchase Requests & Payment Options Loader ---
    def load_requests_from_df(self, requests_df: pd.DataFrame, options_df: Optional[pd.DataFrame] = None) -> List[PurchaseRequest]:
        """Loads purchase requests and associated payment options."""
        self.validate_columns(requests_df, ["request_id", "user_id", "item_name", "full_price"], "requests")

        options_by_req: Dict[str, List[PaymentOption]] = {}
        if options_df is not None:
            self.validate_columns(options_df, ["option_id", "request_id", "type"], "payment_options")
            for _, row in options_df.iterrows():
                opt_id = str(row["option_id"]).strip()
                req_id = str(row["request_id"]).strip()
                type_str = str(row["type"]).strip().upper()

                try:
                    opt_type = PaymentOptionType(type_str)
                except ValueError:
                    raise DataValidationError(f"Invalid payment option type '{type_str}' for option {opt_id}")

                down = self.safe_parse_float(row.get("down_payment", 0.0), "down_payment") or 0.0
                inst_amt = self.safe_parse_float(row.get("installment_amount", 0.0), "installment_amount") or 0.0
                num_inst = int(self.safe_parse_float(row.get("num_installments", 1), "num_installments") or 1)
                freq = int(self.safe_parse_float(row.get("frequency_days", 30), "frequency_days") or 30)
                fee = self.safe_parse_float(row.get("upfront_fee", 0.0), "upfront_fee") or 0.0
                apr = self.safe_parse_float(row.get("apr_percent", 0.0), "apr_percent") or 0.0

                option = PaymentOption(
                    option_id=opt_id,
                    type=opt_type,
                    down_payment=down,
                    installment_amount=inst_amt,
                    num_installments=num_inst,
                    frequency_days=freq,
                    upfront_fee=fee,
                    apr_percent=apr,
                )

                if req_id not in options_by_req:
                    options_by_req[req_id] = []
                options_by_req[req_id].append(option)
                self.payment_options[req_id] = options_by_req[req_id]

        parsed_requests: List[PurchaseRequest] = []
        for _, row in requests_df.iterrows():
            req_id = str(row["request_id"]).strip()
            user_id = str(row["user_id"]).strip()
            item = str(row["item_name"]).strip()
            price = self.safe_parse_float(row["full_price"], "full_price", allow_none=False)
            curr = str(row.get("currency", "USD")).strip().upper() or "USD"
            merchant = str(row.get("merchant")).strip() if pd.notna(row.get("merchant")) else None
            cat = str(row.get("category", "DISCRETIONARY")).strip() or "DISCRETIONARY"
            expires = str(row.get("offer_expires_at")).strip() if pd.notna(row.get("offer_expires_at")) else None
            post_price = self.safe_parse_float(row.get("price_after_expiration"), "price_after_expiration")

            req_options = options_by_req.get(req_id, [
                PaymentOption(option_id=f"OPT_UPFRONT_{req_id}", type=PaymentOptionType.UPFRONT, down_payment=price)
            ])

            req = PurchaseRequest(
                request_id=req_id,
                user_id=user_id,
                item_name=item,
                full_price=price,
                currency=curr,
                merchant=merchant,
                category=cat,
                offer_expires_at=expires,
                price_after_expiration=post_price,
                payment_options=req_options,
            )
            parsed_requests.append(req)

            if user_id not in self.requests:
                self.requests[user_id] = []
            self.requests[user_id].append(req)

        return parsed_requests

    # --- Messages Loader ---
    def load_messages_from_df(self, messages_df: pd.DataFrame) -> List[ChatMessage]:
        """Loads unstructured/semi-structured messages."""
        self.validate_columns(messages_df, ["message_id", "user_id", "sender", "content_text"], "messages")

        parsed_messages: List[ChatMessage] = []
        for _, row in messages_df.iterrows():
            msg_id = str(row["message_id"]).strip()
            user_id = str(row["user_id"]).strip()
            sender = str(row["sender"]).strip()
            text = str(row["content_text"]).strip()
            ts = str(row.get("timestamp", "2026-09-12T00:00:00Z")).strip()
            assoc_evt = str(row.get("associated_event_id")).strip() if pd.notna(row.get("associated_event_id")) and str(row.get("associated_event_id")).strip() != "" else None
            assoc_img = str(row.get("associated_image_id")).strip() if pd.notna(row.get("associated_image_id")) and str(row.get("associated_image_id")).strip() != "" else None

            msg = ChatMessage(
                message_id=msg_id,
                user_id=user_id,
                sender=sender,
                timestamp=ts,
                content_text=text,
                associated_event_id=assoc_evt,
                associated_image_id=assoc_img,
            )
            parsed_messages.append(msg)

            if user_id not in self.messages:
                self.messages[user_id] = []
            self.messages[user_id].append(msg)

        return parsed_messages

    # --- Images Loader ---
    def load_images_from_df(self, images_df: pd.DataFrame) -> List[ImageRecord]:
        """Loads image asset references."""
        self.validate_columns(images_df, ["image_id", "user_id", "file_path_or_url", "image_type"], "images")

        parsed_images: List[ImageRecord] = []
        for _, row in images_df.iterrows():
            img_id = str(row["image_id"]).strip()
            user_id = str(row["user_id"]).strip()
            path = str(row["file_path_or_url"]).strip()
            type_str = str(row["image_type"]).strip().upper()

            try:
                img_type = EvidenceType(type_str)
            except ValueError:
                img_type = EvidenceType.RECEIPT_IMAGE

            uploaded_at = str(row.get("uploaded_at", "2026-09-12T00:00:00Z")).strip()
            linked_evt = str(row.get("linked_event_id")).strip() if pd.notna(row.get("linked_event_id")) and str(row.get("linked_event_id")).strip() != "" else None

            img = ImageRecord(
                image_id=img_id,
                user_id=user_id,
                file_path_or_url=path,
                image_type=img_type,
                uploaded_at=uploaded_at,
                linked_event_id=linked_evt,
            )
            parsed_images.append(img)

            if user_id not in self.images:
                self.images[user_id] = []
            self.images[user_id].append(img)

        return parsed_images

    # --- File-System CSV Ingestion Pipeline ---
    def load_from_directory(self, dir_path: Optional[str] = None) -> Dict[str, Any]:
        """Ingests all CSV files safely from directory if present."""
        target_dir = dir_path or self.dataset_dir
        logger.info(f"Ingesting datasets from directory: {target_dir}")

        if not os.path.exists(target_dir):
            logger.warning(f"Dataset directory '{target_dir}' does not exist. Returning empty loaded state.")
            return {}

        # 1. Exchange Rates
        ex_rates_path = os.path.join(target_dir, "exchange_rates.csv")
        if os.path.exists(ex_rates_path):
            df = pd.read_csv(ex_rates_path)
            self.load_exchange_rates_from_df(df)

        # 2. Accounts & Profiles
        accounts_path = os.path.join(target_dir, "accounts.csv")
        if os.path.exists(accounts_path):
            df = pd.read_csv(accounts_path)
            self.load_user_profiles_from_df(df)

        # 3. Financial Events
        events_path = os.path.join(target_dir, "financial_events.csv")
        if os.path.exists(events_path):
            df = pd.read_csv(events_path)
            self.load_financial_events_from_df(df)

        # 4. Requests & Payment Options
        requests_path = os.path.join(target_dir, "requests.csv")
        options_path = os.path.join(target_dir, "payment_options.csv")
        if os.path.exists(requests_path):
            req_df = pd.read_csv(requests_path)
            opt_df = pd.read_csv(options_path) if os.path.exists(options_path) else None
            self.load_requests_from_df(req_df, opt_df)

        # 5. Messages
        messages_path = os.path.join(target_dir, "messages.csv")
        if os.path.exists(messages_path):
            df = pd.read_csv(messages_path)
            self.load_messages_from_df(df)

        # 6. Images
        images_path = os.path.join(target_dir, "images.csv")
        if os.path.exists(images_path):
            df = pd.read_csv(images_path)
            self.load_images_from_df(df)

        return {
            "profiles_count": len(self.user_profiles),
            "users_with_events": len(self.financial_events),
            "users_with_requests": len(self.requests),
        }

    # --- Clean Relational Data Access Methods ---
    def get_user_profile(self, user_id: str) -> Optional[UserFinancialProfile]:
        """Access user profile by user_id."""
        return self.user_profiles.get(user_id)

    def get_financial_events(self, user_id: str) -> List[FinancialEvent]:
        """Access financial events for a user."""
        return self.financial_events.get(user_id, [])

    def get_requests(self, user_id: str) -> List[PurchaseRequest]:
        """Access purchase requests for a user."""
        return self.requests.get(user_id, [])

    def get_payment_options(self, request_id: str) -> List[PaymentOption]:
        """Access payment options for a purchase request."""
        return self.payment_options.get(request_id, [])

    def get_messages(self, user_id: str) -> List[ChatMessage]:
        """Access text messages for a user."""
        return self.messages.get(user_id, [])

    def get_images(self, user_id: str) -> List[ImageRecord]:
        """Access image assets for a user."""
        return self.images.get(user_id, [])

    def get_linked_evidence(self, event: FinancialEvent) -> Dict[str, Any]:
        """Finds evidence (messages/images) linked to a financial event via linked_event_id."""
        if not event.linked_event_id:
            return {"messages": [], "images": []}

        linked_id = event.linked_event_id
        matching_messages = []
        matching_images = []

        for user_msgs in self.messages.values():
            for m in user_msgs:
                if m.message_id == linked_id or m.associated_event_id == event.event_id:
                    matching_messages.append(m)

        for user_imgs in self.images.values():
            for img in user_imgs:
                if img.image_id == linked_id or img.linked_event_id == event.event_id:
                    matching_images.append(img)

        return {"messages": matching_messages, "images": matching_images}
