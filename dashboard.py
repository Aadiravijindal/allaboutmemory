"""PART 5 — THE CONTROL ROOM. The dashboard humans use.

A single-file Flask app (no build step, no JS framework) that exposes:
  5.1 Search the AI's brain          -> "/" search box
  5.2 Fix and delete everywhere      -> per-memory edit/delete
  5.3 The health score               -> header gauge
  5.4 The approval room              -> "/approvals"
  6.4 The flight recorder            -> "/why/<id>"
  1.3 The diary                      -> "/history/<id>"
  8.*  Insights                      -> "/insights"

Run:  python dashboard.py   (uses vault.db in the current dir)
"""
from __future__ import annotations

import os
from flask import Flask, request, redirect, url_for

from memoryvault import Vault, Policy, Cleaner, Insights

DB = os.environ.get("MV_DB", "vault.db")
POLICY = os.path.join(os.path.dirname(__file__), "policies", "default.yaml")

app = Flask(__name__)


def vault() -> Vault:
    pol = Policy.load(POLICY if os.path.exists(POLICY) else None)
    return Vault(DB, policy=pol)


PAGE = """<!doctype html><html><head><meta charset=utf-8>
<title>MemoryVault — Control Room</title>
<style>
 body{{font:15px/1.5 system-ui,sans-serif;margin:0;background:#0f1220;color:#e7e9f3}}
 header{{background:#171a2e;padding:14px 22px;display:flex;gap:24px;align-items:center;border-bottom:1px solid #2a2f4a}}
 header a{{color:#9fb4ff;text-decoration:none;font-weight:600}}
 .brand{{font-weight:800;color:#fff;font-size:18px}}
 .gauge{{margin-left:auto;font-weight:700;padding:6px 14px;border-radius:20px;background:#1f2440}}
 .A{{color:#5bd68a}} .B{{color:#8fd35b}} .C{{color:#e6c74d}} .D{{color:#e6994d}} .F{{color:#e05b6a}}
 main{{max-width:1000px;margin:0 auto;padding:22px}}
 input,select{{padding:9px 12px;border-radius:8px;border:1px solid #2a2f4a;background:#12162a;color:#e7e9f3}}
 .card{{background:#171a2e;border:1px solid #2a2f4a;border-radius:12px;padding:14px 16px;margin:10px 0}}
 .meta{{color:#8b93b8;font-size:12px;margin-top:6px}}
 .pill{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;background:#242a4a;margin-right:6px}}
 .warn{{color:#e6994d}} .bad{{color:#e05b6a}} .ok{{color:#5bd68a}}
 button,.btn{{padding:7px 12px;border-radius:8px;border:0;background:#3550e0;color:#fff;cursor:pointer;text-decoration:none;font-size:13px}}
 .btn.red{{background:#a33}} .btn.grey{{background:#333a5c}}
 h2{{margin:18px 0 6px}} table{{width:100%;border-collapse:collapse}}
 td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid #232842;font-size:13px}}
</style></head><body>
<header>
 <span class=brand>🧠 MemoryVault</span>
 <a href='/'>Search</a><a href='/approvals'>Approval Room</a>
 <a href='/insights'>Insights</a><a href='/receipts'>Receipts</a>
 <span class='gauge {grade}'>Health: {score} ({grade})</span>
</header><main>{body}</main></body></html>"""


def shell(body: str) -> str:
    h = Insights(vault()).health_score()
    return PAGE.format(body=body, score=h["score"], grade=h["grade"])


@app.route("/")
def home():
    v = vault()
    q = request.args.get("q", "")
    agent = request.args.get("agent", "admin")
    hits = v.search(query=q, agent=agent, limit=100) if q or True else []
    rows = []
    for m in hits:
        badges = f"<span class=pill>{m.namespace}</span>" \
                 f"<span class=pill>{m.provenance.get('source_system')}</span>" \
                 f"<span class=pill>trust {m.trust:.2f}</span>"
        if m.bias_risk:
            badges += "<span class='pill bad'>bias-risk</span>"
        rows.append(f"""<div class=card>
          <div>{m.content}</div>
          <div class=meta>{badges} · id {m.id[:8]} · status {m.status}
             · expires {(m.expires_at or 'never')[:10]}</div>
          <div style='margin-top:8px'>
            <a class='btn grey' href='/history/{m.id}'>History</a>
            <a class='btn grey' href='/why/{m.id}'>Why (flight recorder)</a>
            <a class='btn red' href='/delete/{m.id}'>Delete everywhere</a>
          </div></div>""")
    form = f"""<form method=get style='margin:12px 0'>
      <input name=q placeholder='Search the AI brain… (e.g. acme)'
             value='{q}' size=40>
      <select name=agent>
        {''.join(f"<option {'selected' if a==agent else ''}>{a}</option>"
                 for a in ['admin','sales_agent','support_agent','hr_agent'])}
      </select>
      <button>Search</button></form>"""
    return shell(f"<h2>Search the brain</h2>{form}{''.join(rows) or '<p>No memories yet — run the rescue.</p>'}")


@app.route("/history/<mid>")
def history(mid):
    v = vault()
    events = v.history(mid)
    rows = "".join(
        f"<tr><td>{e['seq']}</td><td>{e['ts'][:19]}</td>"
        f"<td>{e['action']}</td><td>{e['actor']}</td>"
        f"<td>{e['snapshot'].get('value')}</td><td>{e['snapshot'].get('status')}</td>"
        f"<td><a class='btn grey' href='/rollback/{mid}/{e['seq']}'>Undo to here</a></td></tr>"
        for e in events)
    return shell(f"<h2>Diary — memory {mid[:8]}</h2>"
                 f"<table><tr><th>#</th><th>when</th><th>action</th>"
                 f"<th>by</th><th>value</th><th>status</th><th></th></tr>"
                 f"{rows}</table>")


@app.route("/rollback/<mid>/<int:seq>")
def rollback(mid, seq):
    vault().rollback(mid, seq, actor="control_room")
    return redirect(url_for("history", mid=mid))


@app.route("/why/<mid>")
def why(mid):
    v = vault()
    logs = v.retrievals(memory_id=mid)
    rows = "".join(f"<tr><td>{r['ts'][:19]}</td><td>{r['agent']}</td>"
                   f"<td>{r['query']}</td><td>{r['context']}</td></tr>"
                   for r in logs)
    return shell(f"<h2>Flight recorder — memory {mid[:8]}</h2>"
                 f"<p>Everywhere this memory influenced an answer:</p>"
                 f"<table><tr><th>when</th><th>agent</th><th>query</th>"
                 f"<th>context</th></tr>{rows or '<tr><td>not used yet</td></tr>'}</table>")


@app.route("/delete/<mid>")
def delete(mid):
    vault().delete(mid, actor="control_room")
    return redirect(url_for("home"))


@app.route("/approvals")
def approvals():
    v = vault()
    q = v.quarantine_list()
    rows = []
    for m in q:
        rows.append(f"""<div class=card>
          <div class=warn>⚠ {m.content}</div>
          <div class=meta>from {m.provenance.get('source_system')} ·
            channel <b>{m.provenance.get('channel')}</b> · trust {m.trust:.2f}</div>
          <div style='margin-top:8px'>
            <a class=btn href='/approve/{m.id}'>Approve</a>
            <a class='btn red' href='/reject/{m.id}'>Reject</a>
          </div></div>""")
    note = ("<p>These arrived from untrusted sources (email, web, uploads) "
            "and are held OUT of the AI's brain until a human approves them. "
            "This blocks memory-poisoning attacks.</p>")
    return shell(f"<h2>Approval Room ({len(q)})</h2>{note}"
                 f"{''.join(rows) or '<p>Nothing waiting. 🎉</p>'}")


@app.route("/approve/<mid>")
def approve(mid):
    vault().approve(mid, actor="control_room")
    return redirect(url_for("approvals"))


@app.route("/reject/<mid>")
def reject(mid):
    vault().reject(mid, actor="control_room")
    return redirect(url_for("approvals"))


@app.route("/insights")
def insights():
    ins = Insights(vault())
    learned = ins.learned_summary(days=180)
    alerts = ins.signal_alerts()
    spots = ins.blind_spots()
    themes = "".join(f"<span class=pill>{w} ({n})</span>"
                     for w, n in learned["top_themes"])
    alert_rows = "".join(
        f"<div class=card><b class=warn>{a['count']}×</b> pattern "
        f"'<b>{a['pattern']}</b>' — e.g. \"{a['example']}\"</div>"
        for a in alerts)
    spot_rows = "".join(
        f"<tr><td>{ns}</td><td>{d['count']}</td><td>{d['avg_age_days']}d</td>"
        f"<td class='{'bad' if d['risk']=='high' else 'warn' if d['risk']=='medium' else 'ok'}'>"
        f"{d['risk']}</td></tr>" for ns, d in spots.items())
    return shell(f"""
      <h2>8.1 What the AI learned (last 180 days)</h2>
      <div class=card>{learned['memories_learned']} memories · {themes}</div>
      <h2>8.2 Signal alerts</h2>{alert_rows or '<p>No repeated patterns yet.</p>'}
      <h2>8.3 Blind-spot map</h2>
      <table><tr><th>area</th><th>memories</th><th>avg age</th><th>risk</th></tr>
      {spot_rows}</table>""")


@app.route("/receipts")
def receipts():
    v = vault()
    rows = "".join(
        f"<div class=card><b>{r['kind']}</b> · {r['ts'][:19]}"
        f"<div class=meta>hash {r['hash'][:24]}… · "
        f"{r['payload'].get('subject') or r['payload'].get('memory_id','')}</div></div>"
        for r in v.receipts_list())
    return shell(f"<h2>Deletion receipts (GDPR proof)</h2>"
                 f"<p>Tamper-evident, hash-chained proof of every erasure.</p>"
                 f"{rows or '<p>No receipts yet.</p>'}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
