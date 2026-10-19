"""Collect market headlines from public RSS feeds into news.json (runs in GitHub Actions)."""
import json, re, time, html, urllib.request, urllib.parse, email.utils, datetime as dt
import xml.etree.ElementTree as ET

def gnews(q):
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:1d", "hl": "en-US", "gl": "US", "ceid": "US:en"})

FEEDS = [
    ("Google News", gnews("gold price OR XAUUSD OR bullion")),
    ("Google News", gnews("forex dollar euro yen")),
    ("Google News", gnews("Federal Reserve rates inflation")),
    ("Google News", gnews("oil prices Brent WTI OPEC")),
    ("Google News", gnews("stock market S&P 500 Nasdaq")),
    ("Google News", gnews("Sensex Nifty stock market")),
    ("Google News", gnews("Dubai Financial Market OR Abu Dhabi stocks OR Tadawul")),
    ("Google News", gnews("bitcoin crypto market")),
    ("Google News", gnews("site:reuters.com markets")),
    ("Google News", gnews("site:cnbc.com markets")),
    ("Google News", gnews("site:fxstreet.com gold OR forex")),
    ("Google News", gnews("site:kitco.com gold")),
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Investing.com", "https://www.investing.com/rss/news_1.rss"),
    ("Investing.com", "https://www.investing.com/rss/news_11.rss"),
]

TAGS = [
    ("gold", r"\bgold\b|xau|bullion"),
    ("silver", r"\bsilver\b|xag"),
    ("oil", r"\boil\b|crude|brent|wti|opec"),
    ("eurusd", r"eur/?usd|\beuro\b|\becb\b"),
    ("usdjpy", r"usd/?jpy|\byen\b|\bboj\b|bank of japan"),
    ("spx", r"s&p ?500|wall street|\bdow\b|stocks? (rise|fall|close|open)"),
    ("nasdaq", r"nasdaq|\bnvidia\b|\bapple\b|microsoft|big tech|\bai stocks?\b"),
    ("nifty", r"nifty|sensex|\bnse\b|\bbse\b|dalal street|\brbi\b|indian (stocks|shares|markets?)"),
    ("btc", r"bitcoin|\bbtc\b|crypto|ether(eum)?"),
    ("dfm", r"\bdfm\b|dubai (stocks|financial market|index)|abu dhabi|\badx\b|tadawul|saudi (stocks|bourse)|\buae stocks\b|emaar|aramco"),
    ("macro", r"\bfed\b|federal reserve|powell|warsh|inflation|\bcpi\b|\bpce\b|payrolls|jobs report|treasury yields?|rate (hike|cut)"),
]
TRUSTED = [s.lower() for s in [
    "Reuters","Bloomberg","CNBC","FXStreet","Kitco","Kitco NEWS","MarketWatch","Investing.com","Financial Times","The Wall Street Journal","WSJ","Barron's",
    "Yahoo Finance","Associated Press","AP News","BBC","The Guardian","Fortune","Forbes","Business Insider","Axios","CNN","Fox Business","TheStreet",
    "24/7 Wall St.","Benzinga","Seeking Alpha","Morningstar","FOREX.com","DailyFX","FXEmpire","FX Empire","OilPrice.com","S&P Global","Mining.com",
    "World Gold Council","Nikkei Asia","The Japan Times","Euronews","Al Jazeera","Economic Times","The Economic Times","Moneycontrol","Business Standard",
    "Mint","Livemint","The Hindu BusinessLine","BusinessLine","NDTV Profit","Financial Express","The Financial Express","Business Today","CNBC TV18","CNBCTV18",
    "Gulf News","The National","Khaleej Times","Arab News","Zawya","Argaam","Gulf Business","Arabian Business","Asharq Al-Awsat",
    "CoinDesk","The Block","Cointelegraph","Decrypt","Business Recorder","Dawn","South China Morning Post","Nasdaq","Fxempire"]]
def trusted(src):
    s = src.lower().strip()
    return any(s == t or s.startswith(t + " ") or t in s for t in TRUSTED)

BULL = r"\b(rises?|rising|rose|gains?|gained|jumps?|jumped|surges?|surged|rall(y|ies|ied)|climbs?|climbed|soars?|record high|rebounds?|higher|up \d)"
BEAR = r"\b(falls?|falling|fell|drops?|dropped|slides?|slid|slumps?|slumped|tumbles?|tumbled|plunges?|plunged|declines?|declined|sinks?|sank|lower|down \d|sell-?off)"

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (TinasFX news bot; +https://kapiltinasingh-bit.github.io/tinas-fx/)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()

def parse_time(s):
    if not s: return None
    try:
        t = email.utils.parsedate_to_datetime(s)
    except Exception:
        try: t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception: return None
    if t.tzinfo is None: t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc)

def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()
    return re.sub(r"\s+", " ", s)

def main():
    try: old = json.load(open("news.json"))
    except Exception: old = {"items": []}
    items = {i["url"]: i for i in old.get("items", [])}
    status = []
    now = dt.datetime.now(dt.timezone.utc)
    for name, url in FEEDS:
        n = 0
        try:
            root = ET.fromstring(fetch(url))
            entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
            for e in entries[:40]:
                g = lambda tag: (e.findtext(tag) or e.findtext("{http://www.w3.org/2005/Atom}" + tag) or "")
                title = clean(g("title"))
                link = g("link").strip() or (e.find("{http://www.w3.org/2005/Atom}link").get("href") if e.find("{http://www.w3.org/2005/Atom}link") is not None else "")
                src = name
                s_el = e.find("source")
                if s_el is not None and s_el.text: src = clean(s_el.text)
                if name == "Google News" and " - " in title:
                    title, _, tail = title.rpartition(" - ")
                    src = src if src != "Google News" else tail
                t = parse_time(g("pubDate") or g("published") or g("updated"))
                if not title or not link.startswith("http") or not t: continue
                if (now - t).total_seconds() > 3 * 86400 or t > now + dt.timedelta(minutes=10): continue
                if not trusted(src): continue
                if re.search(r"price (today|now)\s*\||live (gold|silver|spot) price|price chart|rates? today in", title.lower()): continue
                low = title.lower()
                tags = [k for k, rx in TAGS if re.search(rx, low)]
                if not tags: continue
                tone = "bullish" if re.search(BULL, low) and not re.search(BEAR, low) else "bearish" if re.search(BEAR, low) and not re.search(BULL, low) else "neutral"
                if link not in items:
                    items[link] = {"title": title[:220], "url": link, "src": src[:60], "t": t.isoformat(), "tags": tags, "tone": tone}
                    n += 1
        except Exception as ex:
            status.append({"feed": name, "url": url[:120], "ok": False, "err": str(ex)[:120]})
            continue
        status.append({"feed": name, "url": url[:120], "ok": True, "new": n})
        time.sleep(0.5)
    # dedupe near-identical titles, newest first, keep 250
    seen, out = set(), []
    for i in sorted(items.values(), key=lambda x: x["t"], reverse=True):
        k = re.sub(r"[^a-z0-9]", "", i["title"].lower())[:70]
        if k in seen: continue
        seen.add(k); out.append(i)
    out = out[:250]
    json.dump({"updated": now.isoformat(), "count": len(out), "feeds": status, "items": out}, open("news.json", "w"), indent=1, ensure_ascii=False)
    ok = sum(1 for s in status if s["ok"])
    print(f"{len(out)} items, {ok}/{len(status)} feeds ok")

if __name__ == "__main__":
    main()
