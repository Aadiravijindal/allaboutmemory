# EU Data Act — Switching & Extraction Playbook

> The legal crowbar behind the Rescue product. Not legal advice; confirm
> specifics with counsel.

## Why this matters
The EU Data Act (Regulation 2023/2854, Chapter VI, applicable from **12 Sep
2025**) gives cloud/SaaS customers a **right to switch providers** and
requires the outgoing provider to:
- allow switching **at any time**, even mid-contract (max 2-month notice);
- **cooperate in good faith** with the receiving provider;
- export the customer's data and "digital assets" in a **commonly used,
  machine-readable format**;
- remove commercial/technical/contractual **obstacles** to switching;
- **eliminate switching fees** entirely by **12 Jan 2027**.

Agent platforms are SaaS. Accumulated agent memory is the customer's data
and digital assets. So a customer has a legal right to extract it — and the
vendor must help.

## The Rescue procedure (what MemoryVault automates)
1. **Customer authorizes** MemoryVault (the receiving provider's tool) to act
   on their behalf.
2. **Invoke the switching right** in writing to the source vendor, citing
   Data Act Ch. VI, requesting a machine-readable export of all memory /
   conversation / learned-context data.
3. **Ingest** the export via `DataActRequestConnector` (CSV/JSON) →
   normalize to CMIF → load into the customer-owned vault.
4. **Verify** with the signed verification report (what was recovered, what
   wasn't, and why).
5. If the vendor stalls, the "good-faith cooperation" and "no obstacles"
   obligations are the escalation lever (regulator complaint if needed).

## Template request letter (to the source vendor)
> Subject: Data Act Chapter VI switching request — [CUSTOMER]
>
> Pursuant to Regulation (EU) 2023/2854, Chapter VI, [CUSTOMER] is exercising
> its right to switch away from [VENDOR]. Please provide, within the
> statutory period, a complete export of all data and digital assets
> associated with our account — including agent memory, conversation
> history, and learned context — in a commonly used, machine-readable
> format, and cooperate in good faith with our receiving provider,
> [YOUR COMPANY], to effect the transfer. Please confirm the export format
> and timeline.

## Notes
- Applies to customers/data in scope of EU law; check territorial scope.
- Interacts with the AI Act's record-keeping duties during switching — keep
  the audit trail (the event log does this automatically).
