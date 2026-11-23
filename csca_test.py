"""CSCA Centre API functional test harness.

Read-only by default. State-changing tests require --allow-write --simulate.
Based on the CSCA Case API and CSCA Library API reference files.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests


CASE_STATUSES = {
    "triage", "ready_to_work", "intake_interview", "scoping_in_progress",
    "gap_response_pending", "gap_analysis", "complete",
}
LIBRARIES = {
    "controls": "control_id",
    "assets": "asset_id",
    "shared-services": "shared_service_id",
    "findings": "finding_code",
}


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def get_field(data, path):
    """Read a dotted JSON field such as questionnaire.questions.0.question_id."""
    current = data
    for name in path.split("."):
        if isinstance(current, dict):
            if name not in current:
                return False, None
            current = current[name]
        elif isinstance(current, list) and name.isdigit():
            index = int(name)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def compare(actual, operator, expected=None):
    if operator == "equals":
        return actual == expected
    if operator == "not_empty":
        return actual is not None and actual != "" and actual != [] and actual != {}
    if operator == "contains":
        return isinstance(actual, (list, str, dict)) and expected in actual
    if operator == "count_at_least":
        return isinstance(actual, (list, dict, str)) and len(actual) >= int(expected)
    if operator == "one_of":
        return actual in expected
    if operator == "is_type":
        types = {"dict": dict, "list": list, "str": str, "int": int, "bool": bool}
        return expected in types and isinstance(actual, types[expected])
    raise ValueError("Unsupported operator: " + operator)


def display_value(value, limit=100):
    """Summarize values without dumping a potentially sensitive case."""
    if isinstance(value, dict):
        return "object with " + str(len(value)) + " keys"
    if isinstance(value, list):
        return "list of " + str(len(value)) + " items"
    text = str(value)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


class CSCAHarness:
    def __init__(self, base_url, credential, auth_type="key", timeout=30,
                 capture_responses=False, session=None, verbose=False):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.capture_responses = capture_responses
        self.verbose = verbose
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        if auth_type == "bearer":
            self.session.headers["Authorization"] = "Bearer " + credential
        else:
            self.session.headers["X-CSCA-Library-Key"] = credential
        self.results = []
        self.exchanges = []
        self.case = None
        self.ritm = None
        self.catalogs = {}

    def record(self, test_id, name, status, details="", method="", path="", http_status=None):
        entry = {
            "id": test_id, "name": name, "result": status, "detail": details,
            "method": method, "endpoint": path, "http_status": http_status,
        }
        self.results.append(entry)
        print(f"{test_id:<18} {status:<6} {name}")
        if self.verbose and details:
            print(" " * 26 + details)
        return status

    def request(self, method, path, params=None, body=None):
        url = self.base_url + path
        start = time.monotonic()
        try:
            response = self.session.request(
                method, url, params=params, json=body, timeout=self.timeout
            )
            duration_ms = round((time.monotonic() - start) * 1000, 1)
        except requests.RequestException as exc:
            return None, None, str(exc), None
        try:
            data = response.json()
        except ValueError:
            data = None
        if self.capture_responses:
            self.exchanges.append({
                "method": method, "path": path, "params": params,
                "request_body": body, "status": response.status_code,
                "duration_ms": duration_ms,
                "response": data if data is not None else response.text,
            })
        return response.status_code, data, "", duration_ms

    def check_get(self, test_id, name, path, expected_type=dict, params=None):
        status, data, error, duration = self.request("GET", path, params=params)
        if status != 200:
            detail = error or f"Expected HTTP 200; received HTTP {status}"
            self.record(test_id, name, "FAIL", detail, "GET", path, status)
            return None
        if not isinstance(data, expected_type):
            self.record(test_id, name, "FAIL", "Unexpected response type", "GET", path, status)
            return None
        self.record(test_id, name, "PASS", f"HTTP {status} ({duration} ms)", "GET", path, status)
        return data

    def check(self, test_id, label, actual, operator, expected=None, evidence=""):
        try:
            passed = compare(actual, operator, expected)
        except (ValueError, TypeError) as exc:
            self.record(test_id, label, "FAIL", str(exc))
            return
        result = "PASS" if passed else "FAIL"
        details = evidence or (f"operator={operator}, expected={display_value(expected)}; "
                               f"observed={display_value(actual)}")
        self.record(test_id, label, result, details)

    def run_read_only(self, ritm=None, expectations=None):
        """API contract and workflow-state checks, without modifying data."""
        case_list = self.check_get("API-001", "List cases", "/cases", params={"limit": 50, "offset": 0})
        if case_list is not None:
            self.check("API-002", "List response contains items", case_list.get("items"), "is_type", "list")
            if isinstance(case_list.get("items"), list):
                self.check("API-003", "Page respects requested limit", len(case_list["items"]) <= 50, "equals", True)
                ids = [x.get("case_id") for x in case_list["items"] if isinstance(x, dict)]
                if len(ids) == len(case_list["items"]) and all(x is not None for x in ids):
                    self.check("API-004", "Cases ordered by case_id", ids, "equals", sorted(ids))
                else:
                    self.record("API-004", "Cases ordered by case_id", "SKIP", "No comparable case IDs")
            self.check("API-005", "Pagination offset present", "offset" in case_list, "equals", True)

        for name, identifier in LIBRARIES.items():
            self.check_library(name, identifier)

        self.check_get("API-020", "Read case metrics", "/metrics")
        self.check_get("API-021", "Read people and roles", "/people", list)

        if not ritm:
            self.record("CASE-000", "Case-specific functional checks", "SKIP", "Pass --ritm or --simulate")
            return

        self.ritm = ritm
        escaped = quote(ritm, safe="")
        case_path = "/cases/" + escaped
        case = self.check_get("CASE-001", "Read full case", case_path)
        if case is None:
            return
        self.case = case
        self.check("CASE-002", "RITM matches requested case", case.get("ritm"), "equals", ritm)
        self.check("CASE-003", "Case identifier exists", case.get("case_id"), "not_empty")
        self.check("CASE-004", "Recognized workflow status", case.get("status"), "one_of", CASE_STATUSES)
        self.check("CASE-005", "Intake object available", case.get("intake"), "is_type", "dict")
        self.check("CASE-006", "Interview structure available", case.get("interview"), "is_type", "dict")
        self.check("CASE-007", "Asset profiles available", case.get("diagram"), "is_type", "dict")
        self.check("CASE-008", "Assigned control list available", case.get("controls"), "is_type", "list")
        self.check("CASE-009", "Questionnaire structure available", case.get("questionnaire"), "is_type", "dict")
        self.check("CASE-010", "GAP analysis structure available", case.get("gap_analysis"), "is_type", "dict")
        self.check("CASE-011", "LIR decision structure available", case.get("low_impact_release"), "is_type", "dict")
        self.check("CASE-012", "Control-test structure available", case.get("control_tests"), "is_type", "list")
        self.check("CASE-013", "Control-test attributes available", case.get("control_test_attributes"), "is_type", "list")
        self.check("CASE-014", "Audit record structure available", case.get("audit_records"), "is_type", "list")

        # As documented, each stage should expose questions/responses when reached.
        interview = case.get("interview")
        if isinstance(interview, dict):
            self.check("WF-001", "Interview questions list", interview.get("questions"), "is_type", "list")
            self.check("WF-002", "Interview submitted answers object", interview.get("submitted_answers"), "is_type", "dict")
        questionnaire = case.get("questionnaire")
        if isinstance(questionnaire, dict):
            self.check("WF-003", "Questionnaire questions list", questionnaire.get("questions"), "is_type", "list")
            self.check("WF-004", "Questionnaire submitted responses list", questionnaire.get("submitted_responses"), "is_type", "list")
        gap = case.get("gap_analysis")
        if isinstance(gap, dict):
            self.check("WF-005", "GAP analysis status exists", gap.get("status"), "not_empty")
        tier = case.get("tier_result")
        if isinstance(tier, dict) and tier.get("final_tier") and case.get("risk_tier"):
            self.check("WF-006", "Calculated tier matches case tier", case.get("risk_tier"), "equals", tier["final_tier"])
        else:
            self.record("WF-006", "Calculated tier matches case tier", "SKIP", "No comparable final tier")

        # The RITM filter is an explicitly documented query option.
        filtered = self.check_get("CASE-015", "Find case by RITM", "/cases", params={"ritm": ritm})
        if filtered is not None and isinstance(filtered.get("items"), list):
            items = filtered["items"]
            self.check("CASE-016", "RITM-filter results match", all(
                isinstance(x, dict) and x.get("ritm") == ritm for x in items
            ), "equals", True)
            self.check("CASE-017", "RITM appears in filtered results", any(
                isinstance(x, dict) and x.get("ritm") == ritm for x in items
            ), "equals", True)
        if expectations:
            self.run_expectations(expectations, case)

    def check_library(self, name, identifier):
        display = name.replace("-", " ").title()
        prefix = {"controls": "LIB-C", "assets": "LIB-A", "shared-services": "LIB-S", "findings": "LIB-F"}[name]
        listing = self.check_get(prefix + "-01", f"List {display}", "/" + name,
                                 params={"limit": 50, "offset": 0})
        if listing is None:
            return
        items = listing.get("items")
        self.check(prefix + "-02", f"{display} list structure", items, "is_type", "list")
        if not isinstance(items, list) or not items:
            self.record(prefix + "-03", f"Read sample {display} record", "SKIP", "No records returned")
            return
        first = items[0]
        if not isinstance(first, dict) or not first.get(identifier):
            self.record(prefix + "-03", f"Read sample {display} record", "SKIP", f"No {identifier} in first item")
            return
        record_id = quote(str(first[identifier]), safe="")
        if name == "assets":
            asset_ritm = first.get("ritm")
            if not asset_ritm:
                self.record(prefix + "-03", f"Read sample {display} record", "SKIP", "No asset RITM")
                return
            path = "/assets/" + quote(str(asset_ritm), safe="") + "/" + record_id
        else:
            path = "/" + name + "/" + record_id
        detail = self.check_get(prefix + "-03", f"Read sample {display} record", path)
        if detail is not None:
            self.check(prefix + "-04", f"{display} ID matches list", detail.get(identifier),
                       "equals", first[identifier])

    def run_expectations(self, definition, case):
        for position, condition in enumerate(definition.get("checks", []), start=1):
            test_id = condition.get("id", f"REQ-{position:03d}")
            label = condition.get("description", condition.get("path", "Unnamed requirement"))
            exists, actual = get_field(case, condition.get("path", ""))
            if not exists:
                self.record(test_id, label, "FAIL", "Missing JSON path: " + condition.get("path", ""))
                continue
            self.check(test_id, label, actual, condition.get("operator", "equals"),
                       condition.get("expected"))

    def simulate_case(self):
        """Explicitly create a sample only when the CLI authorizes writes."""
        status, data, error, duration = self.request("POST", "/cases/simulate")
        if status == 503:
            self.record("SIM-001", "Create mock case", "SKIP", "Simulation disabled on server",
                        "POST", "/cases/simulate", status)
            return None
        if status != 201 or not isinstance(data, dict):
            self.record("SIM-001", "Create mock case", "FAIL",
                        error or f"Expected HTTP 201, received {status}",
                        "POST", "/cases/simulate", status)
            return None
        ritm = data.get("ritm")
        if not ritm or "MOCK" not in str(ritm).upper():
            self.record("SIM-001", "Create mock case", "FAIL",
                        "Simulation response did not contain an identifiable MOCK RITM")
            return None
        self.record("SIM-001", "Create mock case", "PASS", f"RITM={ritm}",
                    "POST", "/cases/simulate", status)
        return ritm

    def run_workflow(self, definition, ritm):
        """Execute only user-specified steps against a newly simulated RITM."""
        escaped = quote(ritm, safe="")
        for position, step in enumerate(definition.get("steps", []), start=1):
            test_id = step.get("id", f"WRITE-{position:03d}")
            name = step.get("description", "Workflow step")
            method = step.get("method", "").upper()
            template = step.get("path", "")
            allowed_paths = {
                "/cases/{ritm}", "/cases/{ritm}/lir", "/cases/{ritm}/interview",
                "/cases/{ritm}/assets", "/cases/{ritm}/controls",
                "/cases/{ritm}/questionnaire",
            }
            if "MOCK" not in ritm.upper():
                self.record(test_id, name, "FAIL", "Writes require a server-generated MOCK RITM")
                continue
            if method not in ("POST", "PATCH") or template not in allowed_paths:
                self.record(test_id, name, "FAIL", "Only documented case workflow paths are permitted")
                continue
            path = template.replace("{ritm}", escaped)
            status, data, error, duration = self.request(method, path, body=step.get("body"))
            expected_status = step.get("expected_status", 200)
            if status != expected_status:
                self.record(test_id, name, "FAIL", error or f"HTTP {status}, expected {expected_status}", method, path, status)
                continue
            if not isinstance(data, dict):
                self.record(test_id, name, "FAIL", "Expected a JSON object", method, path, status)
                continue
            failures = []
            for condition in step.get("assertions", []):
                found, actual = get_field(data, condition.get("path", ""))
                try:
                    valid = found and compare(actual, condition.get("operator", "equals"),
                                              condition.get("expected"))
                except (ValueError, TypeError):
                    valid = False
                if not valid:
                    failures.append(condition.get("path", ""))
            if failures:
                self.record(test_id, name, "FAIL", "Response assertions failed: " + ", ".join(failures), method, path, status)
            else:
                self.record(test_id, name, "PASS", f"HTTP {status}; {len(step.get('assertions', []))} assertions", method, path, status)
            # Verify persistence independently, rather than trusting write response.
            read_path = "/cases/" + escaped
            latest = self.check_get(test_id + "-GET", "Read case after write", read_path)
            if latest is not None:
                for count, condition in enumerate(step.get("assertions", []), start=1):
                    found, actual = get_field(latest, condition.get("path", ""))
                    if found:
                        self.check(test_id + f"-P{count}", "Persisted " + condition["path"],
                                   actual, condition.get("operator", "equals"), condition.get("expected"))
                    else:
                        self.record(test_id + f"-P{count}", "Persisted " + condition["path"], "FAIL", "JSON path missing")

    def save_reports(self, folder, timestamp):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        counts = {status: sum(x["result"] == status for x in self.results)
                  for status in ("PASS", "FAIL", "SKIP")}
        body = {
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "base_url": self.base_url, "ritm": self.ritm,
            "summary": counts, "tests": self.results,
        }
        txt_path = folder / f"CSCA_Functional_Test_{timestamp}.txt"
        json_path = folder / f"CSCA_Functional_Test_{timestamp}.json"
        lines = ["CSCA CENTRE — API FUNCTIONAL TEST REPORT", "=" * 82,
                 "Generated UTC: " + body["generated_utc"],
                 "Target: " + self.base_url, "RITM: " + str(self.ritm or "N/A"),
                 f"Results: PASS={counts['PASS']}  FAIL={counts['FAIL']}  SKIP={counts['SKIP']}", "",
                 f"{'TEST ID':<20} {'RESULT':<7} {'DESCRIPTION':<48} HTTP", "-" * 90]
        for result in self.results:
            lines.append(f"{result['id']:<20} {result['result']:<7} {result['name'][:48]:<48} "
                         + (str(result['http_status']) if result['http_status'] else ""))
            if result["result"] != "PASS" or self.verbose:
                if result["detail"]:
                    lines.append("    " + result["detail"])
        txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        json_path.write_text(json.dumps(body, indent=2, default=str), encoding="utf-8")
        if self.capture_responses:
            capture_path = folder / f"CSCA_Trace_{timestamp}.json"
            capture_path.write_text(json.dumps(self.exchanges, indent=2, default=str), encoding="utf-8")
            print("Captured full API traffic:", capture_path, "(may contain sensitive data)")
        print("Text report:", txt_path)
        print("JSON report:", json_path)
        return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description="CSCA Centre API functional testing")
    parser.add_argument("--base-url", default=os.getenv("CSCA_BASE_URL"),
                        help="API root including /libraries/v1, e.g. https://host/libraries/v1")
    parser.add_argument("--ritm", help="Existing RITM to inspect (read-only)")
    parser.add_argument("--expect", help="JSON file of business requirements to compare with case response")
    parser.add_argument("--out-dir", default="csca_test_results", help="Directory for test reports")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--verbose", action="store_true", help="Print detailed test evidence")
    parser.add_argument("--capture-responses", action="store_true",
                        help="Save full API requests and responses (sensitive data warning)")
    parser.add_argument("--simulate", action="store_true", help="Create a server-side mock case (write)")
    parser.add_argument("--allow-write", action="store_true", help="Authorize writes to a mock case")
    parser.add_argument("--workflow", help="JSON instructions for changing the created mock case")
    parser.add_argument("--allow-http", action="store_true", help="Allow HTTP (credentials sent unencrypted)")
    args = parser.parse_args(argv)
    if not args.base_url:
        parser.error("Provide --base-url or set CSCA_BASE_URL")
    if not args.base_url.startswith("https://"):
        if not args.allow_http or not args.base_url.startswith("http://"):
            parser.error("HTTPS required; for an isolated HTTP test server pass --allow-http")
    if args.workflow and not args.simulate:
        parser.error("--workflow requires --simulate (never modifies an existing RITM)")
    if args.simulate and not args.allow_write:
        parser.error("--simulate requires explicit --allow-write")
    if args.simulate and args.ritm:
        parser.error("Choose --simulate or --ritm, not both")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    key = os.getenv("CSCA_LIBRARY_KEY")
    bearer = os.getenv("CSCA_BEARER_TOKEN")
    if bearer:
        credential, auth_type = bearer, "bearer"
    elif key:
        credential, auth_type = key, "key"
    else:
        parser.error("Set CSCA_LIBRARY_KEY or CSCA_BEARER_TOKEN (do not put tokens on CLI)")
    try:
        expectations = read_json(args.expect) if args.expect else None
        workflow = read_json(args.workflow) if args.workflow else None
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    test = CSCAHarness(args.base_url, credential, auth_type=auth_type, timeout=args.timeout,
                       capture_responses=args.capture_responses, verbose=args.verbose)
    timestamp = utc_stamp()
    ritm = args.ritm
    if args.simulate:
        ritm = test.simulate_case()
    test.run_read_only(ritm=ritm, expectations=expectations)
    if workflow and ritm:
        test.run_workflow(workflow, ritm)
    counts = test.save_reports(args.out_dir, timestamp)
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
