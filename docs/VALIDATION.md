# Validation

The following checks ran on 10 September 2026.

| Check | Result |
| --- | --- |
| Backend controls | 19 tests passed: authentication, CSRF header, scoped RBAC, duplicate controls, immutable final data, approval roles, idempotent retries, rate/claim/invoice ceilings, import atomics, attachment authorization, worker authentication. |
| Worker | 2 tests passed: authenticated refresh and surfaced API failure. |
| Frontend production build | Passed: TypeScript compilation and Vite build. |
| Browser smoke test | Passed at desktop and mobile sizes: login, control tower, chart switch, search, HSE entry, upload, two-stage approval, drawer navigation, dialog Escape handling, and no horizontal mobile overflow. |
| Docker Compose | Passed after first-run MySQL retry fix: db, API, web gateway, and worker all reported healthy/running. `/api/health`, demo dashboard, and worker alert refresh returned successfully. |

Docker Desktop was left running with the explicitly opted-in demo stack at `http://127.0.0.1:8080`. Stop it with `docker compose -p mone-coalchain down` when it is no longer needed; named volumes are preserved.
