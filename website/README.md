# MemoryVault — marketing site

The public website. **Kept entirely separate from the product code** — nothing
here imports from the application, and nothing here reveals how to reach it.
One self-contained file, no build step, no dependencies, no external requests.

```
website/
  index.html   the entire site (HTML + CSS + JS inlined)
  README.md
```

## Run it locally (to edit)

Open `index.html` in a browser, or serve the folder:

```bash
cd website && python3 -m http.server 8123
```

## Deploy it

A single static file, so any host works with no configuration:

- **Netlify / Vercel / Cloudflare Pages** — point the project at this directory,
  no build command, publish directory `website`.
- **GitHub Pages** — serve `/website` from the branch.
- **S3 / nginx** — copy `index.html` and serve it.

## Access is gated on purpose

There is deliberately **no repository link, no install instructions, no public
sandbox, and no trial credentials** anywhere on this page. The only way in is
the request-access form. A memory layer with a public front door would fail its
own security review, and that argument is made on the page itself.

If you add anything to this site, keep it that way: no product URLs, no
internal endpoint names, no build or test details.

## Wiring the form to a real inbox

The form validates in the browser, then hands the details to the visitor's mail
client and shows a confirmation. That keeps the page fully static with no
backend to run. To route submissions somewhere else, replace the `location.href
= "mailto:…"` line in the submit handler with a `fetch()` to whichever endpoint
you use (Formspree, HubSpot, your own API). The field names are already set on
each input, so a plain form POST works too.

Change `founders@memoryvault.dev` to the real address in three places: the
submit handler, the confirmation panel, and the footer/investor links.

## What's on the page

The page is one argument, in order.

| Section | Job it does |
|---|---|
| Hero | The one-liner, the live activity strip, the vault graph |
| Problem | Three things that already happened: poisoned email, unapproved refund, lock-in |
| Why now | Poisoning is a named risk category; leakage is the #1 buyer concern; approvals take 8–16 weeks |
| Insight | Memory is the company's record, and it needs a front door, a receipt and an exit |
| Product | The eight console rooms, each labelled with the person who cares |
| Gate demo | Two facts reach the checkpoint; one is cleared, one is rejected |
| How it works | The data-flow diagram — the thing security reviews actually stall on |
| Where we stand | Recall vs retrieval vs control, without naming competitors |
| ROI | Two sliders, live figure, anchored on the reference $36,024 |
| Trace | A row that opens into provenance, sealed history, and which agents read it |
| Security | Six controls, then the "shorten your own review" bar |
| Integrations | The AI tools and workplace apps it connects to |
| Partners | HKU and Jindal India, plus the open design-partner slots |
| Access | The 4-step process and the request form |
| Investors | Wedge, why now, moat, model, where we are |

## Positioning (why the copy reads the way it does)

Competitors were read before any copy was written:

- **Memory SDKs** sell to a developer: an API so one app remembers its users,
  measured in tokens and latency.
- **Context graph platforms** sell to a platform team: sharper retrieval,
  measured in benchmark accuracy and milliseconds. Several already carry SOC 2
  and enterprise deployment options, so "we're the enterprise one" is *not* a
  differentiator.
- Neither can answer: who approved this fact, prove it wasn't altered, hand it
  back when we leave, or what it's worth in dollars.

Hence the line the page is built around: **other tools make your AI remember
more; we decide what it is allowed to believe.** Every section either supports
that claim or gets cut.

Buyer research drove two sections that a generic AI landing page wouldn't have:
the **data-flow diagram** (vague architecture answers are what stall security
reviews) and the **8–16 week review bar** (approvals run long across 10+
stakeholders, so the pitch is that we shorten the review rather than survive it).

## Interactive pieces

All functional, not styled mockups:

- **Vault graph** — canvas 2D: ~94 nodes on a Fibonacci sphere, depth-sorted
  edges, two counter-rotating dial rings, and pulses travelling edge to edge.
  Eased pointer parallax. The canvas has explicit CSS dimensions so bitmap
  writes can't feed back into layout, and a `ResizeObserver` handles the fact
  that the hero is still laying out when the script first runs.
- **Live activity feed** — cycles governance events every 2.2s.
- **Gate animation** — travel distances are computed from the lane's measured
  width, so the cards land exactly on the checkpoint line at any viewport.
- **ROI calculator** — the product's own assumptions (6 min per reuse, $60/hr,
  $12,000 per prevented incident). Defaults land on $36,000.
- **Trace drawer** — expands to provenance, sealed history and reader list.
- **Request form** — real validation (name, work email format, company), then a
  prefilled draft and an on-page confirmation.
- **Command palette** — `⌘K` / `Ctrl-K`, arrow keys, Enter to navigate.

## Constraints honored

- **No external requests.** No CDN, no web fonts, no analytics, no tracking. It
  renders identically behind a strict CSP or on a plane.
- **No emoji.** Every icon is an inline SVG symbol in a single sprite.
- Loads in well under a second; the canvas is the only animation loop and it
  idles while its box has no size.
- `prefers-reduced-motion` disables the graph, the feed loop, the gate
  animation, the card tilt and every scroll reveal — all content stays readable.
- No horizontal overflow at 390px; grid tracks carry `min-width:0` so cards
  shrink instead of pushing the page sideways.
- Body, muted and accent text all clear 4.5:1 on the dark background.
- Semantic landmarks, one `h1`, labelled form controls, `aria-expanded` on the
  trace row, and visible focus styles.

## Editing copy

Everything is literal text in `index.html` — no CMS, no JSON. Figures that
appear in more than one place (the $36,024 reference, ~65%, 83%/80%, 8–16
weeks) come from the product spec and buyer research; if those change, update
them here too.
