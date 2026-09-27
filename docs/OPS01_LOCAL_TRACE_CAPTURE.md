# OPS01 local correlated trace capture

This procedure demonstrates request-level correlation in a local development
environment. It is not an incident capture, a production measurement, or a
query-plan report.

## Safety and scope

- Use a dedicated local SQLite database or a reviewed disposable database with
  synthetic data. Never point this capture at production.
- `LOCAL_TRACE_CAPTURE_ENABLED` defaults to `false` and application startup
  rejects it in production, staging, or other public runtimes.
- The trace records a generated request ID, HTTP method, matched route
  template, status, app duration, count of attempted SQL executions, and
  aggregate SQL execution duration. It does not record SQL text, bind values,
  headers, query strings, cookies, request/response bodies, or user identifiers.
- Browser HAR files can still contain credentials, cookies, URLs, and business
  data. Keep captures outside the repository in a restricted local directory;
  do not attach or share an unsanitized HAR.

## Capture steps

1. Configure a local-only backend environment with `ENV=development`,
   `LOCAL_TRACE_CAPTURE_ENABLED=true`, a dedicated SQLite `DATABASE_URL`, and
   a test-only `INITIAL_ADMIN_PASSWORD`. Use the application's local startup
   migration/seed path to create synthetic rows; do not reuse a shared or
   production database URL.
2. Start the backend and the frontend against that local backend. Keep the
   terminal containing backend logs visible, and note the UTC capture time
   alongside the retained `request_trace` lines.
3. In browser DevTools Network, enable Preserve log, clear prior requests, and
   perform one bounded read-only page load. Record the wall-clock time and
   inspect the matching API response's `X-Request-ID` and `Server-Timing`
   headers. For a HAR, save to the restricted directory described above.
4. Find the backend `request_trace` line with the same request ID. It reports
   the route template, status, total application time, attempted SQL execute
   count, and aggregate database execution time. Match the browser waterfall
   by request URL/method and compare its waiting/transfer timing with
   `Server-Timing`.
5. Repeat the same action a few times and retain each request ID separately;
   do not merge unrelated requests into one sample. Note frontend/API errors,
   proxy status, response size, and concurrent load separately.
6. If a query needs plan investigation, reproduce it on a reviewed disposable
   PostgreSQL database with representative synthetic data and run a read-only
   `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for that SELECT. The request trace
   intentionally contains no SQL text or query fingerprint and does not claim
   to identify an individual statement's plan.

## Automated local verification

From `backend/`, run:

```powershell
python -m pytest -p no:cacheprovider app/tests/test_request_trace_capture.py
```

The API regression verifies the response/log correlation, database timing
fields, and absence of a query-string secret or SQL text. Separate checks
verify the opt-in default and the production/public runtime guard. These tests
use the existing isolated synthetic SQLite fixture; they provide no shared
incident-window evidence.
