#!/usr/bin/env python3
"""`python setup_check.py` — shows exactly what your pasted keys activated.

Run this after editing .env to confirm what's live vs demo.
"""
from memoryvault.config import CONFIG
from memoryvault.connectors_live import live_systems


def main():
    a = CONFIG.activated()
    print("\n  MemoryVault — activation status")
    print("  " + "=" * 44)
    print(f"  Storage      : {a['storage']}")
    print(f"  Encryption   : {a['encryption']}")
    print(f"  Embeddings   : {a['embeddings']}")
    print(f"  Billing      : {a['billing']}")
    live = live_systems()
    if live:
        print(f"  LIVE connectors ({len(live)}):")
        for s in live:
            print(f"      ✓ {s}")
    else:
        print("  Connectors   : demo (fixtures) — paste a token in .env to go live")
    print("  " + "=" * 44)
    missing = []
    if not CONFIG.database_url:
        missing.append("DATABASE_URL (Postgres) — using SQLite demo")
    if not CONFIG.encrypt:
        missing.append("MV_ENCRYPT + KMS — encryption off")
    if not live:
        missing.append("a connector token — using fixtures")
    if not CONFIG.stripe_secret_key:
        missing.append("STRIPE_SECRET_KEY — billing metered locally only")
    if missing:
        print("  To go fully live, paste in .env:")
        for m in missing:
            print(f"      • {m}")
    else:
        print("  ✅ Fully live — production config detected.")
    print()


if __name__ == "__main__":
    main()
