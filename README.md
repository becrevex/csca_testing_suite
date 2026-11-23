# CSCA Centre — API Functional Testing Harness

A small, readable Python utility for checking the documented CSCA Centre API against expected behavior. It uses `requests`, the two supplied API reference files, and JSON assertion files for case-specific business requirements. **Read-only by default.**

The source files describe a single API root, `/libraries/v1`, and support either `X-CSCA-Library-Key` or an approved Okta bearer token. The API host itself is not included in the files: supply your environment's real host.

## Setup (PowerShell)

```powershell
py -m pip install requests
$env:CSCA_BASE_URL = "https://YOUR-INTERNAL-HOST/libraries/v1"
$env:CSCA_LIBRARY_KEY = "YOUR_AUTHORIZED_KEY"
# Or set CSCA_BEARER_TOKEN instead of CSCA_LIBRARY_KEY.
```

**Do not hard-code or commit credentials.** TLS certificate verification is enabled by default. If both authentication variables are set, the bearer token takes precedence.

## Running tests

**Basic read-only API smoke checks:**

```powershell
python .\csca_test.py
```

**Read an existing case and verify the exposed workflow records:**

```powershell
python .\csca_test.py --ritm RITM1234567 --verbose
```

**Compare a case to expected functional requirements:**

```powershell
python .\csca_test.py --ritm RITM1234567 --expect .\requirements.example.json
```

Edit `requirements.example.json` to specify the actual expected outcomes for a known RITM. These examples demonstrate the format; they are *not* approved CSCA Centre requirements.

**Capture HTTP request/response JSON for reproducible defects:**

```powershell
python .\csca_test.py --ritm RITM1234567 --verbose --capture-responses
```

**CAUTION:** Full traces may contain sensitive customer, employee, application, or assessment information. Only use `--capture-responses` on authorized systems, keep reports in an approved secured location, and sanitize before sharing.

## Workflow testing (explicitly modifies a sample case)

The documented `POST /cases/simulate` endpoint creates a mock case, but the server normally disables it in production. It may return 503. The harness requires **both** flags below and will accept workflow mutations only for a newly simulated MOCK RITM:

```powershell
python .\csca_test.py --simulate --allow-write --workflow .\workflow.example.json --verbose
```

`workflow.example.json` performs the documented triage transition with a sample `service_team=Cloud`. Adjust the team and prerequisites to match your sandbox's approved test data. Subsequent steps can use the documented POST/PATCH paths below, with JSON request bodies and expected response assertions. No automatic cleanup or rollback is performed; simulated cases remain in the test environment.

If simulation is disabled, the harness records SKIP rather than forcing a write. **Do not enable simulation or run mutation tests in production just to satisfy the harness.**

The optional workflow step format is:

```json
{
  "steps": [
    {
      "id": "WF-EXAMPLE",
      "description": "Example state transition",
      "method": "PATCH",
      "path": "/cases/{ritm}",
      "body": {"status": "ready_to_work", "service_team": "Cloud"},
      "expected_status": 200,
      "assertions": [
        {"path": "status", "operator": "equals", "expected": "ready_to_work"}
      ]
    }
  ]
}
```

The harness performs a GET after each workflow write to verify the value was persisted, not merely echoed back. It only permits these documented workflow mutation paths: `/cases/{ritm}`, `/cases/{ritm}/interview`, `/cases/{ritm}/assets`, `/cases/{ritm}/controls`, `/cases/{ritm}/questionnaire`, and `/cases/{ritm}/lir`. It does **not** call case import, ServiceNow integration, evidence upload, report issuance, library mutation, or deletion endpoints.

## Requirement assertions

`--expect` accepts a JSON object with `checks`. Every check has `id`, `description`, `path`, `operator`, and (when needed) `expected`.

Supported operators: `equals`, `not_empty`, `contains`, `count_at_least`, `one_of`, and `is_type` (`dict`, `list`, `str`, `int`, `bool`). A JSON path uses dot notation, e.g. `risk_tier`, `tier_result.final_tier`, `questionnaire.questions.0.question_id`, or `low_impact_release.status`.

Each check has a separate test ID for traceability. A missing property causes FAIL, not a false PASS.

## Output

Every run creates two files in `./csca_test_results` (or another `--out-dir`):

- `CSCA_Functional_Test_YYYYMMDD_HHMMSSZ.txt` — fixed-width PASS/FAIL/SKIP matrix.
- `CSCA_Functional_Test_YYYYMMDD_HHMMSSZ.json` — test IDs, results, endpoint, HTTP status, and explanations.

With `--capture-responses`, an additional `CSCA_Trace_YYYYMMDD_HHMMSSZ.json` contains the complete HTTP requests/responses. Without that flag, response bodies are not copied into the report. Exit code is `1` if any test fails, otherwise `0`.

## Coverage boundaries

See `TEST_MATRIX.md` for the endpoint-by-endpoint traceability overview.

The two supplied API reference files provide read/write operations for triage, interview, assets, controls, questionnaire, LIR, notes, GAP status, and library records. There is no described dedicated endpoint to execute *advisor validation* or *control-audit* decisions, so this harness currently checks only the GET-visible `control_tests`, `control_test_attributes`, and `audit_records` structures. This does **not** prove those workflows function correctly. Likewise, the harness does not invent the workbook's risk scoring, tier assignment, control applicability, validation pass/fail, or attestation rules. Those should be added as explicit expectations with trusted fixtures once their expected results are provided.

## Offline tests

```powershell
python -m unittest -v test_csca_test.py
```

The tests mock HTTP responses and never call your real CSCA Centre environment.
