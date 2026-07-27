# ADR 0005: API Rate Limiting

Status: Accepted

Date: 2026-06-18

## Context

The app already rate-limits failed login and password reset activity, but other endpoints can still be abused by repeated requests. A full distributed rate limiter requires shared infrastructure that is not yet part of the deployment.

## Decision

Add a lightweight in-process global rate limiter in FastAPI. Keep authentication-specific rate limits for login and password reset.

## Consequences

- A single backend process gets basic abuse protection immediately.
- Multi-process or multi-instance deployments should move the global limiter to Redis or provider edge controls.
- `/health` and CORS preflight requests are exempt.
