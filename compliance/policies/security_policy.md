# Information Security Policy (template — review with counsel/auditor)

**Company:** [YOUR COMPANY]  ·  **Effective:** [DATE]  ·  **Owner:** CISO/CTO

## 1. Purpose
Protect the confidentiality, integrity, and availability of customer AI
memory processed by MemoryVault.

## 2. Scope
All systems, staff, and contractors handling customer data or the
MemoryVault production environment.

## 3. Data classification
- **Customer memory** — Confidential. Encrypted at rest (customer KMS) and
  in transit. Isolated per tenant. Never accessed by [COMPANY] staff except
  under a break-glass procedure with customer consent and audit.
- **Control-plane metadata** (tenants, API keys, usage) — Internal.

## 4. Access control
- Least privilege; RBAC enforced (owner/admin/operator/reviewer/readonly).
- MFA required for all production access.
- Access reviewed quarterly; removed within 24h of offboarding.

## 5. Encryption
- At rest: AES-256 envelope encryption; keys in the customer's KMS.
- In transit: TLS 1.2+.

## 6. Logging & monitoring
- Admin actions, deletions, and memory retrievals are logged (immutable,
  hash-chained). Logs retained [12 months].

## 7. Incident response
See `incident_response.md`. Customers notified within [72 hours] of a
confirmed breach affecting their data.

## 8. Vendor management
Sub-processors listed in the DPA; reviewed annually.

## 9. Change management
All production changes via version control + CI + peer review.

## 10. Business continuity
Automated backups (14-day retention), multi-AZ, quarterly recovery test.

---
*This is a starting template, not legal advice. Have counsel and your SOC 2
auditor review before adoption.*
