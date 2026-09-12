"""
Unit tests for FastAPI REST API Routes
Tests:
- POST /api/decision
- GET /api/requests
- GET /api/requests/{request_id}
- GET /api/health
- Structured error response formatting (code, message)
- 404 handling for non-existent requests
- Error handling without stack trace leaks
"""

import unittest
from fastapi.testclient import TestClient
from app.main import app


class TestAPIRoutes(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def test_1_health_check(self):
        """GET /api/health returns status ok."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")

    def test_2_post_decision(self):
        """POST /api/decision accepts Stitch request format and returns complete decision."""
        payload = {
            "product": "Laptop",
            "amount": 60000,
            "desired_date": "2026-09-30",
        }

        response = self.client.post("/api/decision", json=payload)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn("request_id", data)
        self.assertIn("amount_safe_to_pay", data)
        self.assertIn("affordability_status", data)
        self.assertIn("recommended_payment_method", data)
        self.assertIn("payment_plan", data)
        self.assertIn("earliest_date_for_full_payment", data)
        self.assertIn("spending_changes_needed", data)
        self.assertIn("decision_explanation", data)

        req_id = data["request_id"]

        # Test GET /api/requests
        hist_res = self.client.get("/api/requests")
        self.assertEqual(hist_res.status_code, 200)
        history = hist_res.json()
        self.assertTrue(len(history) >= 1)
        self.assertTrue(any(item["request_id"] == req_id for item in history))

        # Test GET /api/requests/{request_id}
        single_res = self.client.get(f"/api/requests/{req_id}")
        self.assertEqual(single_res.status_code, 200)
        single_data = single_res.json()
        self.assertEqual(single_data["request_id"], req_id)
        self.assertEqual(single_data["amount_safe_to_pay"], data["amount_safe_to_pay"])

    def test_3_get_nonexistent_request_returns_structured_404(self):
        """GET /api/requests/NONEXISTENT_ID returns structured error format."""
        response = self.client.get("/api/requests/NONEXISTENT_999")
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertIn("error", data)
        self.assertEqual(data["error"]["code"], "NOT_FOUND")
        self.assertIn("message", data["error"])

    def test_4_invalid_payload_returns_structured_400(self):
        """POST /api/decision with negative amount returns structured error."""
        payload = {
            "product": "Negative Item",
            "amount": -500.0,
        }

        response = self.client.post("/api/decision", json=payload)
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("error", data)
        self.assertEqual(data["error"]["code"], "INVALID_REQUEST")
        self.assertIn("message", data["error"])


if __name__ == "__main__":
    unittest.main()
