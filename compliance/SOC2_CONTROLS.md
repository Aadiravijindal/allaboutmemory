# SOC 2 Type II — Control Mapping (Trust Services Criteria)

This maps the SOC 2 controls to where they're **already implemented in
code** vs what the **audit** still needs (people/process/time). Hand this to
Vanta/Drata to jump-start the audit — the technical controls are done.

Legend: ✅ implemented in code · 📋 policy doc (in `compliance/policies/`) ·
🧑 human/process step for the auditor

## CC6 — Logical & Physical Access
| Control | Status | Evidence |
|---|---|---|
| CC6.1 Logical access controls | ✅ | `tenancy.py` RBAC + API-key auth |
| CC6.1 Encryption at rest | ✅ | `crypto.py` envelope encryption via customer KMS |
| CC6.1 Encryption in transit | 🧑 | TLS at the load balancer (Terraform/Helm ingress) |
| CC6.2 Access provisioning | ✅ | `ControlPlane.issue_key` roles; 🧑 approval workflow |
| CC6.3 Access removal | ✅ | key revocation; 📋 offboarding policy |
| CC6.6 Least privilege | ✅ | `ROLE_CAPS`, namespace ACL walls |
| CC6.7 Data isolation (multi-tenant) | ✅ | per-org vault isolation |

## CC7 — System Operations
| Control | Status | Evidence |
|---|---|---|
| CC7.1 Vulnerability monitoring | 🧑 | dependency scanning in CI; pen test |
| CC7.2 Security event logging | ✅ | admin audit log + flight recorder |
| CC7.2 Anomaly detection | ✅ | Approval Room (poisoning), 🧑 SIEM |
| CC7.3 Incident response | 📋 | `compliance/policies/incident_response.md` |
| CC7.4 Backups & recovery | 🧑 | RDS automated backups (Terraform, 14-day) |

## CC8 — Change Management
| CC8.1 Change control | ✅ | CI (`.github/workflows/ci.yml`), Git, PR review |

## A1 — Availability
| A1.1 Capacity | 🧑 | Fargate autoscaling / HPA |
| A1.2 Backups & DR | 🧑 | RDS snapshots, multi-AZ |
| A1.3 Recovery testing | 🧑 | quarterly DR drill |

## C1 — Confidentiality
| C1.1 Confidential data identified | ✅ | provenance + namespace + PII tags |
| C1.2 Disposal | ✅ | delete-with-receipt, retention TTL |

## P — Privacy (GDPR / EU Data Act overlap)
| Right to erasure | ✅ | `erase_subject` + signed receipt |
| Data portability | ✅ | CMIF export (the whole product) |
| Records of processing | ✅ | event log + flight recorder |

## What the audit still needs (🧑 — cannot be code)
1. **A monitoring vendor** (Vanta/Drata) connected to the cloud account.
2. **~3–6 months of evidence collection** (Type II observes controls over time).
3. **An independent auditor** (a CPA firm) to issue the report.
4. **A penetration test** by a security firm.
5. **HR/process policies signed** (the `compliance/policies/` drafts below).

Start the vendor + auditor now; the code controls above are already in place,
which is the part most startups spend months building.
