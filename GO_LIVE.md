# Go Live — paste keys, and it works

Everything that *can* be code is done and config-driven. To take MemoryVault
from demo to production, you paste credentials into `.env` and (for infra)
run one deploy command. Here's the whole checklist.

```bash
cp .env.example .env      # then paste keys below
python setup_check.py     # shows exactly what activated
```

## 1. Storage → Postgres  (paste `DATABASE_URL`)
```
DATABASE_URL=postgres://user:pass@host:5432/memoryvault
```
Provisioned automatically by the Terraform below, or point at your own PG
(needs the `vector` extension). `pip install "psycopg[binary]"`.

## 2. Encryption → your KMS  (paste `MV_KMS_KEY_ID`)
```
MV_ENCRYPT=1
MV_KMS_PROVIDER=aws
MV_KMS_KEY_ID=arn:aws:kms:...:key/....
```
`pip install boto3`. Keys stay in your account — we can't read your data.

## 3. Connectors → paste a token, that platform goes live
```
MEM0_API_KEY=...                 # Mem0 migration goes live
SALESFORCE_TOKEN=...             # + SALESFORCE_INSTANCE_URL
MS_GRAPH_TOKEN=...               # Microsoft Copilot
INTERCOM_TOKEN=...
ZEP_API_KEY=...
OPENAI_EXPORT_FILE=/path/export.json   # ChatGPT Enterprise
```
`pip install requests`. Each token flips its connector from demo fixtures to
the real vendor API — no code change. Verify with `python setup_check.py`.

## 4. Real embeddings  (paste `OPENAI_API_KEY`)
```
MV_EMBEDDINGS=openai
OPENAI_API_KEY=...
```

## 5. Billing → Stripe  (paste `STRIPE_SECRET_KEY`)
```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PLATFORM=price_...
STRIPE_PRICE_CONNECTOR=price_...
```
`pip install stripe`. Usage is metered locally regardless; Stripe turns it
into invoices. Webhook: `POST /api/billing/webhook`.

## 6. BYOC deploy → one command
**AWS (Terraform):**
```bash
cd deploy/terraform && terraform init
terraform apply -var="db_password=..." -var="image=ghcr.io/you/memoryvault:latest"
# outputs: KMS ARN, DB endpoint — paste back into .env
```
**Any Kubernetes (Helm):**
```bash
helm install memoryvault ./deploy/helm/memoryvault \
  --set image.repository=ghcr.io/you/memoryvault \
  --set env.DATABASE_URL=... --set env.MV_KMS_KEY_ID=...
```

## 7. Durable sync → already on
`POST /api/durable/enqueue?kind=full` runs a retried, dead-lettered sync.
Set `MV_SYNC_INTERVAL` and start the scheduler for the "runs all day" loop.

---

## What still needs a human (no key can do these)
| Item | Who | Artifact we shipped |
|---|---|---|
| **SOC 2 audit** | Vanta/Drata + a CPA auditor, ~3–6 mo | `compliance/SOC2_CONTROLS.md` (controls already coded) + `compliance/policies/` |
| **Penetration test** | a security firm | scope from `docs/SECURITY.md` |
| **Sign the DPA / ToS** | your lawyer | `legal/DPA_template.md`, `legal/TERMS_template.md` |
| **Data Act requests** | you send them | `legal/DATA_ACT_PLAYBOOK.md` (letter template inside) |
| **First 3 design partners** | you | the Rescue demo is your pitch |

The code is done. These five are the human half of building the company —
we've shipped every artifact they need so only the signature/audit remains.
