# Data Processing Agreement (DPA) — TEMPLATE

> ⚠️ **Not legal advice.** A starting draft to hand to counsel. Bracketed
> fields need completion; a lawyer must review before use.

**Between:** [CUSTOMER] ("Controller") and [YOUR COMPANY] ("Processor")

## 1. Subject matter
Processor provides MemoryVault, a service that stores, governs, and
synchronizes the Controller's AI agent memory.

## 2. Nature & purpose of processing
Extraction, storage, deduplication, governance, and synchronization of
memory records across the Controller's AI platforms, on the Controller's
instructions.

## 3. Categories of data
- AI-generated memory records (may contain personal data the Controller's
  agents captured: names, contact details, preferences, interaction notes).
- The Controller determines what its agents write; Processor does not decide
  purposes.

## 4. Roles
Controller = data controller. Processor processes only on documented
instructions (Art. 28 GDPR).

## 5. Sub-processors
Listed in Annex A. Cloud infrastructure runs in the **Controller's own
account (BYOC)** where elected; Processor has no standing access to
plaintext customer memory (customer-held KMS keys).

## 6. Security measures (Art. 32)
Encryption at rest (customer KMS) and in transit; tenant isolation; RBAC;
immutable audit logging; poisoning defense (Approval Room); tamper-evident
event chain. See `compliance/SOC2_CONTROLS.md`.

## 7. Data subject rights
Processor provides tooling for erasure (`erase_subject`, signed receipt),
portability (CMIF export), and records of processing (event log) to help the
Controller meet Art. 15–20 requests.

## 8. Breach notification
Processor notifies Controller without undue delay and within [72 hours] of
becoming aware of a personal-data breach.

## 9. Deletion / return
On termination, Processor deletes or returns all customer memory within
[30 days] and certifies deletion (chain-bound receipt).

## 10. Audits
Processor makes available its SOC 2 report and reasonable audit support.

## 11. International transfers
[SCCs / adequacy — complete per jurisdiction.]

## Annex A — Sub-processors
| Sub-processor | Purpose | Location |
|---|---|---|
| [Cloud provider] | Hosting (BYOC = customer's own account) | [region] |
| [Stripe] | Billing metadata only (no memory) | [US/EU] |
