# ADR 0001: Browser Auth Uses HttpOnly Cookies

Status: Accepted

Date: 2026-06-18

## Context

The ERP is used from a browser and contains operational, finance, employee, and customer data. Earlier documentation referenced browser-readable JWT storage in `localStorage`, which increases exposure if frontend JavaScript is compromised.

## Decision

Browser login uses `/api/auth/login` and stores the session token in an HttpOnly, SameSite=Lax cookie. Machine clients may still use `/api/auth/token` and bearer tokens.

## Consequences

- Browser JavaScript cannot read the auth token.
- Frontend requests must use same-origin credentials through the Next.js proxy.
- Unsafe browser requests need CSRF origin protection.
- Logout clears the auth cookie.
