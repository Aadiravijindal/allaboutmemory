# MemoryVault — marketing site

The public website. **Completely separate from the product code** in
`memoryvault/` and `web/` — nothing here imports from or is imported by the
application. One self-contained file, no build step, no dependencies.

```
website/
  index.html   the entire site (HTML + CSS + JS inlined)
  README.md
```

## Run it

Open `index.html` directly in a browser, or serve the folder:

```bash
cd website && python3 -m http.server 8123
# → http://localhost:8123
```

## Deploy it

It's a static file, so any host works with zero configuration:

- **Netlify / Vercel / Cloudflare Pages** — drag the folder in, or point the
  project at this directory with no build command and `website` as the
  publish directory.
- **GitHub Pages** — set Pages to serve `/website` from the branch.
- **S3 / nginx** — copy `index.html` and serve it.

## What's on the page

The page is one argument, in order: the problem already happened → why it's
urgent now → the insight → the product → where we stand → what it's worth →
why you can trust it → how to run it → the ask.

| Section | Purpose |
|---|---|
| Hero | The one-liner, plus a live activity feed and the animated vault graph |
| Problem | Three vignettes: poisoned email, unauthorized refund, vendor lock-in |
| Why now | OWASP ASI06, ~65% of AI failures from bad memory, 6+ ungoverned agents |
| Product | The eight console rooms, each with a mock of the real UI |
| Gate demo | Two memories reach the checkpoint — one approved, one rejected |
| Where we stand | Positioning against recall-focused and retrieval-focused tools |
| ROI calculator | Two sliders, live dollar figure, anchored on the product's $36K |
| Trace drawer | Clickable row expanding into provenance, hash chain, and readers |
| Trust | Audit chain, receipts, kill switch, model governance, GDPR/DPDP |
| Integrations | The AI vendors and workplace tools it connects to |
| Quick start | The real 4-command local run |
| Social proof | Empty slots ready for design-partner logos |
| For investors | Wedge, why-now, moat, model, and what exists today |

## Interactive pieces

All of these are functional, not styled mockups:

- **Vault graph** — canvas 2D, ~90 nodes on a Fibonacci sphere with
  depth-sorted edges, counter-rotating dial rings, and pulses travelling
  edge to edge. Re-measures via `ResizeObserver`; the canvas has explicit
  CSS dimensions so bitmap writes can't feed back into layout.
- **Live activity feed** — cycles real log lines from the product's audit
  vocabulary every 2.2s.
- **ROI calculator** — uses the product's own assumptions (6 min saved per
  reuse, $60/hr loaded cost, $12,000 per prevented incident). Defaults land
  on $36,000, matching the demo vault's audited figure.
- **Gate animation** — travel distances are computed from the lane's real
  width so the cards land on the gate line at any viewport size.
- **Trace drawer** — click or keyboard-activate the row; `aria-expanded`
  tracks state.
- **Command palette** — `⌘K` / `Ctrl-K`, filterable, Enter navigates.

## Constraints honored

- No external requests: no CDN, no web fonts, no analytics. A strict CSP or
  an offline laptop renders it identically.
- Loads in well under a second; the canvas is the only animation loop and it
  idles when the box has no size.
- `prefers-reduced-motion` disables the graph, the feed loop, the gate
  animation, and all scroll reveals — content stays fully readable.
- No horizontal overflow at 390px; grid tracks carry `min-width:0` so cards
  shrink instead of pushing the page sideways.
- Semantic landmarks (`nav`/`header`/`main`/`section`/`footer`), real heading
  order, and body text kept above 4.5:1 contrast on the dark background.

## Editing copy

Everything is literal text in `index.html` — no CMS, no JSON blob. The
numbers that appear in more than one place ($36K, ~65%, ASI06, 82 tests)
come from the product spec; if the product's figures change, update them
here too.
