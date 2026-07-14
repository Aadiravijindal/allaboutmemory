# Incident Response Plan (template)

## Roles
- **Incident Commander:** [NAME]
- **Security Lead / Comms / Eng on-call:** [NAMES]

## Severity
- **SEV1** — customer data exposure/loss; production down.
- **SEV2** — degraded service; potential exposure.
- **SEV3** — minor, contained.

## Phases
1. **Detect** — alert from monitoring, Approval Room anomaly, or report.
2. **Triage** — assign severity + Incident Commander within 30 min.
3. **Contain** — revoke keys, isolate tenant, disable connector, or
   `rollback_since` to pre-incident memory state.
4. **Eradicate & recover** — patch, restore from backup, verify chain
   integrity (`verify_chain`).
5. **Notify** — affected customers within [72h] for confirmed breaches
   (GDPR Art. 33/34). Regulator as required.
6. **Post-mortem** — blameless review within 5 business days; track actions.

## Evidence
Preserve: audit log, flight-recorder retrievals, event chain, deadletters.

## Contacts
- Customers: per DPA notification clause.
- Regulators: [DPA / supervisory authority].
- Auditor / insurer: [CONTACTS].
