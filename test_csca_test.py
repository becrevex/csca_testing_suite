import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import csca_test


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, routes=None):
        self.routes = routes or {}
        self.headers = {}
        self.calls = []

    def request(self, method, url, params=None, json=None, timeout=30):
        self.calls.append((method, url, params, json, timeout))
        path = url.split("/libraries/v1", 1)[-1]
        result = self.routes.get((method, path))
        if isinstance(result, list):
            return result.pop(0)
        if result is None:
            return FakeResponse(404, {"error": "not found"})
        return result


def fixture_case():
    return {
        "ritm": "RITM_TEST_001-MOCK", "case_id": "c-1", "status": "triage",
        "intake": {"assessment_type": "New IT System"},
        "interview": {"questions": [], "submitted_answers": {}},
        "diagram": {"asset_profiles": []}, "controls": [],
        "questionnaire": {"questions": [], "submitted_responses": []},
        "gap_analysis": {"status": "not_started"},
        "low_impact_release": {}, "control_tests": [], "control_test_attributes": [],
        "audit_records": [], "tier_result": {"final_tier": "Tier 2"},
        "risk_tier": "Tier 2", "service_team": "Cloud"
    }


def fake_routes():
    case = fixture_case()
    routes = {
        ("GET", "/cases"): FakeResponse(200, {"items": [
            {"case_id": "c-1", "ritm": "RITM_TEST_001-MOCK"}],
            "limit": 50, "offset": 0, "next_offset": None}),
        ("GET", "/cases/RITM_TEST_001-MOCK"): FakeResponse(200, case),
        ("GET", "/metrics"): FakeResponse(200, {"total_assessments": 1}),
        ("GET", "/people"): FakeResponse(200, []),
    }
    for name, key in csca_test.LIBRARIES.items():
        routes[("GET", "/" + name)] = FakeResponse(200, {"items": [{key: "sample", "ritm": "RITM_TEST_001-MOCK"}], "next_offset": None})
        detail_path = "/" + name + "/sample"
        if name == "assets":
            detail_path = "/assets/RITM_TEST_001-MOCK/sample"
        routes[("GET", detail_path)] = FakeResponse(200, {key: "sample"})
    return routes


class DataHelpersTests(unittest.TestCase):
    def test_get_field_nested(self):
        self.assertEqual(csca_test.get_field({"a": {"b": 2}}, "a.b"), (True, 2))

    def test_get_field_array(self):
        self.assertEqual(csca_test.get_field({"a": [{"b": 3}]}, "a.0.b"), (True, 3))

    def test_get_field_missing(self):
        self.assertEqual(csca_test.get_field({"a": []}, "a.9"), (False, None))

    def test_equals(self):
        self.assertTrue(csca_test.compare("A", "equals", "A"))

    def test_not_empty(self):
        self.assertFalse(csca_test.compare("", "not_empty"))

    def test_contains(self):
        self.assertTrue(csca_test.compare(["A", "B"], "contains", "B"))

    def test_count_at_least(self):
        self.assertTrue(csca_test.compare([1, 2], "count_at_least", 2))

    def test_one_of(self):
        self.assertTrue(csca_test.compare("triage", "one_of", csca_test.CASE_STATUSES))

    def test_is_type(self):
        self.assertTrue(csca_test.compare([], "is_type", "list"))

    def test_unknown_operator(self):
        with self.assertRaises(ValueError):
            csca_test.compare(1, "undefined")


class APITests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession(fake_routes())
        self.harness = csca_test.CSCAHarness("https://example.invalid/libraries/v1", "not-a-real-key", session=self.session)

    def test_key_header(self):
        self.assertEqual(self.session.headers["X-CSCA-Library-Key"], "not-a-real-key")

    def test_bearer_header(self):
        other = FakeSession()
        csca_test.CSCAHarness("https://example.invalid/libraries/v1", "test", auth_type="bearer", session=other)
        self.assertEqual(other.headers["Authorization"], "Bearer test")

    def test_list_only(self):
        self.harness.run_read_only()
        self.assertFalse(any(x["result"] == "FAIL" for x in self.harness.results))
        self.assertTrue(any(x["id"] == "CASE-000" for x in self.harness.results))

    def test_single_case(self):
        self.harness.run_read_only("RITM_TEST_001-MOCK")
        self.assertFalse(any(x["result"] == "FAIL" for x in self.harness.results))
        self.assertTrue(any(x["id"] == "WF-006" and x["result"] == "PASS" for x in self.harness.results))

    def test_failure_status(self):
        self.session.routes[("GET", "/metrics")] = FakeResponse(403, {"error": "access denied"})
        self.harness.run_read_only()
        self.assertTrue(any(x["id"] == "API-020" and x["result"] == "FAIL" for x in self.harness.results))

    def test_case_expectations(self):
        self.harness.run_read_only("RITM_TEST_001-MOCK", {"checks": [
            {"id": "REQ-1", "path": "status", "operator": "equals", "expected": "triage"}
        ]})
        self.assertTrue(any(x["id"] == "REQ-1" and x["result"] == "PASS" for x in self.harness.results))

    def test_case_expectations_fail(self):
        self.harness.run_read_only("RITM_TEST_001-MOCK", {"checks": [
            {"id": "REQ-1", "path": "status", "operator": "equals", "expected": "complete"}
        ]})
        self.assertTrue(any(x["id"] == "REQ-1" and x["result"] == "FAIL" for x in self.harness.results))

    def test_simulation_enabled(self):
        self.session.routes[("POST", "/cases/simulate")] = FakeResponse(201, fixture_case())
        self.assertEqual(self.harness.simulate_case(), "RITM_TEST_001-MOCK")

    def test_simulation_disabled(self):
        self.session.routes[("POST", "/cases/simulate")] = FakeResponse(503, {"error": "disabled"})
        self.assertIsNone(self.harness.simulate_case())
        self.assertEqual(self.harness.results[-1]["result"], "SKIP")

    def test_simulation_bad_response(self):
        self.session.routes[("POST", "/cases/simulate")] = FakeResponse(500, {"error": "server"})
        self.assertIsNone(self.harness.simulate_case())
        self.assertEqual(self.harness.results[-1]["result"], "FAIL")

    def test_write_workflow(self):
        updated = fixture_case()
        updated["status"] = "ready_to_work"
        self.session.routes[("PATCH", "/cases/RITM_TEST_001-MOCK")] = FakeResponse(200, updated)
        self.session.routes[("GET", "/cases/RITM_TEST_001-MOCK")] = FakeResponse(200, updated)
        self.harness.run_workflow({"steps": [{
            "id": "STEP-1", "method": "PATCH", "path": "/cases/{ritm}",
            "body": {"status": "ready_to_work"},
            "assertions": [{"path": "status", "operator": "equals", "expected": "ready_to_work"}]
        }]}, "RITM_TEST_001-MOCK")
        self.assertFalse(any(x["result"] == "FAIL" for x in self.harness.results))
        self.assertEqual(sum(x["result"] == "PASS" for x in self.harness.results), 3)

    def test_write_noncase_disallowed(self):
        self.harness.run_workflow({"steps": [{"method": "POST", "path": "/controls"}]}, "RITM_TEST_001-MOCK")
        self.assertEqual(self.harness.results[-1]["result"], "FAIL")
        self.assertEqual(len(self.session.calls), 0)

    def test_reports_created(self):
        self.harness.run_read_only()
        with tempfile.TemporaryDirectory() as folder:
            count = self.harness.save_reports(folder, "20261123_010000Z")
            self.assertEqual(count["FAIL"], 0)
            self.assertTrue(Path(folder, "CSCA_Functional_Test_20261123_010000Z.txt").exists())
            self.assertTrue(Path(folder, "CSCA_Functional_Test_20261123_010000Z.json").exists())

    def test_capture_default_disabled(self):
        self.harness.request("GET", "/metrics")
        self.assertEqual(self.harness.exchanges, [])

    def test_capture_explicit(self):
        self.harness.capture_responses = True
        self.harness.request("GET", "/metrics")
        self.assertEqual(len(self.harness.exchanges), 1)


if __name__ == "__main__":
    unittest.main()
