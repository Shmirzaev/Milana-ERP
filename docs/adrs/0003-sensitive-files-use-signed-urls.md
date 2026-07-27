# ADR 0003: Sensitive Files Use Signed URLs

Status: Accepted

Date: 2026-06-18

## Context

Some uploaded files need to render in browser contexts where an `Authorization` header is not practical. Serving them as public static files would expose customer-supplied production assets to anyone with the URL.

## Decision

Sales-order printing attachments are served only through short-lived HMAC-signed URLs. Model files remain authenticated.

## Consequences

- File URLs expire.
- The file signing secret must be different from the JWT secret.
- The backend validates path traversal and keeps file access under configured storage roots.
