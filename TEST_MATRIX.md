# CSCA Centre — Initial Functional Test Matrix

**Source:** The supplied `csca_cases_api_helper.txt` and `csca_libraries_api_helper.txt` (both document OpenAPI 3.1, API root `/libraries/v1`). Test IDs below belong to this harness; they are not official CSCA requirement IDs.

| Workflow | API | Current automated coverage | Further validation needed |
|---|---|---|---|
| Intake / Ready-to-Work | `GET /cases`, `GET /cases/{ritm}` | List, RITM filter, full case, intake record, status, ordering | Verify fields sourced from ServiceNow/CMDB against trusted intake fixture |
| Triage / Ready-to-Work transition | `PATCH /cases/{ritm}` | User-defined workflow step on simulated case, verify persisted status and team | Server transition restrictions; assigned advisor and prework requirements |
| Interview / Prerequisites | `GET /cases/{ritm}`, `POST /cases/{ritm}/interview` | Question/answer object shapes; optional simulated submit with expected result | Correct question generation, gated controls, interview prerequisites |
| Asset profiling / Diagram | `GET /cases/{ritm}`, `POST /cases/{ritm}/assets` | Profile/asset structures; optional simulated submit and persistence | Asset-to-control applicability, parsing correctness, shared service relationships |
| Control scope | `PATCH /cases/{ritm}/controls` | Assigned controls list; optional simulated control-list update | Tier/assessment type/asset-specific control applicability against baseline workbook |
| Questionnaire | `POST /cases/{ritm}/questionnaire` | Question/response structures and optional simulated submission | Expected question set; conditional questions; artifacts and inherited evidence |
| GAP / Validation | `GET /cases/{ritm}` | GAP status structure; detailed control-test and attribute structures exist | GAP decision logic, PASS/FAIL/FAIL (Mitigated), review outcomes and advisor notes require approved expected outcomes and/or missing API functions |
| Low Impact Release | `POST /cases/{ritm}/lir` | LIR structure; optional simulated decision | Eligibility gates, mandatory answers, accepted/declined transitions |
| Control Audit | `GET /cases/{ritm}` | Audit record *shape* only | No dedicated control-audit write/test endpoint in either uploaded file; cannot validate execution or advisor decisions |
| Library controls | `GET /controls`, `GET /controls/{control_id}` | List, detail fetch, identifier consistency | Control definitions, revisions, tier/asset/assessment applicability rules |
| Asset library | `GET /assets`, `GET /assets/{ritm}/{asset_id}` | List, detail fetch, identifier consistency | Asset ownership and associated control relationships |
| Shared services | `GET /shared-services`, `GET /shared-services/{shared_service_id}` | List, detail fetch, identifier consistency | Attribute satisfaction and inheritance rules |
| Finding templates | `GET /findings`, `GET /findings/{finding_code}` | List, detail fetch, identifier consistency | Finding generation and control/attribute mapping |
| Service users / metrics | `GET /people`, `GET /metrics` | Response type and status only | Role permissions and calculated metric correctness |

## Known limitations

1. The helpers are Swagger/OpenAPI reference text, not a verified running environment. This code was tested against mocks only; server connectivity, permissions, API version, and response variations are unverified.
2. No actual RITM, expected CSCA workbook output, or approved validation fixtures were supplied. The example requirements are illustrative and must be edited before claiming functional acceptance.
3. GET contract checks are not complete end-to-end functional validation. They identify integration failures and gross structural inconsistencies; they cannot verify business outcomes without an expected result.
4. Workflow writes are disabled by default, restricted to the simulation endpoint's mock RITM, and require explicit authorization. Simulation may be disabled.
5. No API write/DELETE call is performed on library controls, shared services, findings, or assets by this harness.
