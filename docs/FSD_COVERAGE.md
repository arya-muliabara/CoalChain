# FSD Coverage

This implementation follows `FSD_Mining_Contractor_Management_System-1.docx`. The table records the delivered initial release rather than implying that every target end-state feature is complete.

| FSD area | Initial release | Notes |
| --- | --- | --- |
| Master data and RBAC | Delivered | Site, pit/block/seam, location/route, contractor, equipment; role/site/contractor scope; user administration. |
| Contract and rates | Delivered | Contract, rate, amendment, historical audit, effective rate/date/distance validation, utilization. |
| Planning and DPR | Delivered | Monthly planning, manpower, equipment status, DPR, hauling, verified-production workflow. |
| Survey and reconciliation | Delivered | Survey volume control, multistage approval, allocation control, configurable tolerance and exception resolution. |
| Fleet and fuel | Delivered | Equipment availability/utilization/productivity from DPR; fuel entries and OB fuel ratio alert. |
| Performance and HSE | Delivered | Configurable score weights, scorecard, HSE records, HSE/availability/production/fuel alerts. |
| Claim, billing, cost | Delivered | Server-side rate/claim calculation, retention, configurable penalty/incentive rules with evidence, invoice ceiling, payment recording, cost view. |
| Dashboard and audit | Delivered | Control tower, monthly filters, KPI cards/charts, alerts, approval inbox, audit trail. |
| Documents and imports | Delivered | Versioned attachments, CSV export, CSV/XLSX preview-validation-confirmation import. |
| Mobile and PWA | Delivered with limits | Responsive browser UI, install manifest, cached shell, local offline drafts for DPR/fuel/HSE. No offline database or background sync. |
| REST API | Delivered | Internal API and OpenAPI docs. External adapters are not configured. |
| Notifications | Partial | In-app operational alerts and worker heartbeat. Email, mobile push, and external API notifications are future integration work. |
| Coal quality / weighbridge / lab | Not delivered | The data model and integration boundary are ready, but source-system mapping is required. |
| GPS / dispatch integration | Not delivered | Hauling is entered/imported manually in this release. |
| ERP / SAP / Odoo | Not delivered | Claim and payment records are internal; no posting connector is shipped. |
| Advanced forecasting / anomaly AI | Not delivered | Phase 4 requires reliable production history, model governance, and agreed decision ownership. |
| Object-storage antivirus retention | Not delivered | Local/Docker document volume is suitable for initial deployment; enterprise document storage and scanning are required for production scale. |

## Business rules implemented

- **BR-001:** Claims require approved reconciliation and verified production; invoices require approved claims.
- **BR-002 / BR-011:** Final survey and other approved transactions are immutable; controlled reopen is audited and blocked if downstream records exist.
- **BR-003:** Claim rate is selected server-side from exactly one active approved rate.
- **BR-004:** Contractor user reads/writes only its contractor scope.
- **BR-005 / BR-006:** Invoice ceiling and claim contract value/quantity ceiling are enforced. Amendments can raise limits after approval.
- **BR-007:** DPR natural key prevents duplicate date, shift, equipment, activity, and pit combinations.
- **BR-008 / BR-009:** Fuel and operating records require valid, period-active equipment in the chosen contractor/site scope.
- **BR-010:** Penalty and incentive calculation evidence is stored with the claim.
