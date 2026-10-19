# Tina's FX

Gold (XAU/USD) research desk: live spot price, live TradingView chart, key levels, desk calls, research archive, news wire and founder letter.

## Files

- `index.html` — the whole site (design, layout, logic)
- `catalog.json` — every market on the site, grouped by asset class, with its TradingView symbol
- `learn.json` — Academy lessons and the glossary
- `news.json` — live news wire, refreshed every 15 minutes by the GitHub Action in `.github/workflows/news.yml` (script: `scripts/fetch_news.py`)
- `data.json` — everything the research desk updates: price snapshot, levels, desk call, call record, research posts, news, macro numbers
- `tina-dubai.jpg` — founder photo
- `.nojekyll` — tells GitHub Pages to serve files as-is

## Turn on GitHub Pages

1. Repository → **Settings** → **Pages**
2. Source: **Deploy from a branch** → Branch: `main`, folder `/ (root)` → **Save**
3. After about a minute the site is live at `https://<your-username>.github.io/<repo-name>/`

## Custom domain (optional)

Buy a domain (for example tinasfx.com), add it under Settings → Pages → Custom domain, and point the domain's DNS to GitHub Pages as GitHub instructs.

## How it updates

- Spot price: every minute in the visitor's browser, from gold-api.com
- Chart: streamed live by TradingView
- Levels, desk call, research, news: the Tina's FX research run edits `data.json` four times each weekday (06:20, 10:20, 15:20 and 20:20 Dubai time)
- Live prices and signal status: the Signal watcher Action (`scripts/watch.py`) publishes `live.json` to the `live` branch about once a minute

Educational research only. Not financial advice.
