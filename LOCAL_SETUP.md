# Run MemoryVault on your MacBook — the complete guide

## Part A — Run it (3 minutes, no keys needed)

Open **Terminal** (Cmd+Space → "Terminal") and paste:

```bash
cd ~/Desktop
git clone https://github.com/Aadiravijindal/allaboutmemory.git
cd allaboutmemory
chmod +x run.sh
./run.sh
```

That's it. It installs everything and starts the app. Open in your browser:

- **http://localhost:8000** — the dashboard → click **Run Rescue**
- **http://localhost:8000/react** — the React UI (has the **Connect** tab)
- **http://localhost:8000/api/docs** — the full API

Stop it with **Ctrl+C**. Run it again anytime with `./run.sh`.

Other commands:
```bash
./run.sh test     # run all 42 tests
./run.sh demo     # terminal walkthrough of all 8 parts
./run.sh full     # install the optional API packages too
```

---

## Part B — Turn on the real APIs (optional)

Everything works on demo data with zero keys. To make integrations **real**,
paste keys into the `.env` file (created for you on first run):

```bash
open -e .env       # opens .env in TextEdit
```

Paste any of these — each one activates automatically on restart. You only
need the ones you want; skip the rest.

| Paste this in `.env` | What it turns on | Where to get it |
|---|---|---|
| `OPENAI_API_KEY=sk-...` | Smart LLM cleanup of messy exports + real semantic search | platform.openai.com → API keys |
| `MEM0_API_KEY=...` | Live memory transfer to/from Mem0 | mem0.ai (free tier) |
| `SALESFORCE_TOKEN=...` + `SALESFORCE_INSTANCE_URL=...` | Live Salesforce connector | your Salesforce → Setup → OAuth |
| `INTERCOM_TOKEN=...` | Live Intercom support memory | Intercom → Developer Hub |
| `ZEP_API_KEY=...` | Live Zep connector | getzep.com |
| `MS_GRAPH_TOKEN=...` | Live Microsoft Copilot | Azure AD app registration |
| `STRIPE_SECRET_KEY=sk_test_...` | Real billing/subscriptions | dashboard.stripe.com → API keys |
| `WORKOS_API_KEY=...` + `WORKOS_CLIENT_ID=...` | Enterprise SSO login | workos.com |
| `DATABASE_URL=postgres://...` | Big Postgres database instead of the demo file | any Postgres w/ pgvector |
| `MV_ENCRYPT=1` + `MV_KMS_KEY_ID=...` | "We can't read your data" encryption | AWS Console → KMS |

Then, so the optional packages are installed:

```bash
./run.sh full      # installs openai, stripe, boto3, workos, psycopg
```

Check what activated any time:
```bash
source venv/bin/activate
python setup_check.py
```
It prints a clear list: what's **live** vs still on **demo**.

---

## The honest reality of "all APIs"

- **Free/instant to turn on:** OpenAI (a few dollars), Mem0 (free tier),
  Stripe (test mode is free). Do these first — they make the biggest
  difference in a demo.
- **Needs your company's admin:** Salesforce, Microsoft, Intercom tokens —
  these require access to *those* accounts, so you'll only have them for a
  real customer (or your own test tenant).
- **Cloud infra:** Postgres, AWS KMS — worth doing only when you deploy for
  a real customer, not for local testing.

**For running on your Mac to show people:** you don't need ANY keys — the
demo data already shows the whole product. Add `OPENAI_API_KEY` if you want
the "smart cleanup" to look extra impressive. That's genuinely all you need
locally.

---

## Troubleshooting

- **"command not found: python3"** → `brew install python` (install Homebrew
  first from brew.sh if needed).
- **"command not found: git"** → `xcode-select --install`.
- **port 8000 busy** → run `uvicorn memoryvault.api:app --port 8080` and use
  `localhost:8080`.
- **anything red on install** → copy the error to me and I'll fix it.
