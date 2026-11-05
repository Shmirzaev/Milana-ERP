# Local audit-switch stress plan — written before execution

- Target: isolated audit candidate at `d19e6c91`, local PostgreSQL project `milana-idn01-audit-browser`; never production.
- Scenario: after MIL→ECO→MIL readback, send two concurrent authorized `POST /api/auth/switch-factory` requests for ECO using the same still-valid MIL token. Both are real requests from MIL and should each append one audit row. Then make one denied ECO request as the MIL-only account.
- Duration/volume: two concurrent requests, one small burst, 10-second stop limit, two expected audit rows; no repeated load loop.
- Limits: each response ≤5 seconds; zero HTTP 5xx or unexpected refusal; exactly two additional complete `switch_factory` rows with actor/from/to/time/hash; audit chain verifies; no user assignment/grant change. Stop and report on any timeout, storage error or unexpected response.
