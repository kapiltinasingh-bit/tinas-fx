"""Tina's FX signal watcher.

Runs for a fixed number of minutes, once a minute:
  * pulls live prices for every desk market (Yahoo Finance chart API; gold and
    silver spot from gold-api.com, with futures candles shifted by the measured
    futures-minus-spot gap),
  * walks 1-minute candles through every open trade plan in data.json and marks
    each side waiting -> filled -> T1 -> T2 / breakeven / stopped / expired,
  * publishes live.json to the `live` branch as a single force-pushed commit
    (so it never triggers a Pages rebuild or bloats history).

Grading rules match the research desk prompt: a "limit" plan fills when price
touches the trigger; any other plan fills when price trades through it. If the
stop and a target print in the same candle, the stop is assumed first.
"""
import json, os, subprocess, sys, time, urllib.parse, urllib.request, datetime as dt

GST = dt.timezone(dt.timedelta(hours=4))
UA = {"User-Agent": "Mozilla/5.0 (TinasFX watcher)"}
SYM = {"gold": "GC=F", "silver": "SI=F", "oil": "CL=F", "eurusd": "EURUSD=X", "usdjpy": "JPY=X",
       "spx": "^GSPC", "nasdaq": "^IXIC", "nifty": "^NSEI", "btc": "BTC-USD", "dfm": "DFMGI.AE"}
SPOT = {"gold": "XAU", "silver": "XAG"}
TERMINAL = {"stopped", "t2", "be", "expired"}


def get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def chart(sym, interval="1m", rng="1d"):
    s = urllib.parse.quote(sym, safe="")
    j = get(f"https://query2.finance.yahoo.com/v8/finance/chart/{s}?interval={interval}&range={rng}")
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    bars = []
    for i, t in enumerate(r.get("timestamp") or []):
        h, l, c = q["high"][i], q["low"][i], q["close"][i]
        if None not in (h, l, c):
            bars.append((t, h, l, c))
    return r["meta"], bars


def iso(ts):
    return dt.datetime.fromtimestamp(ts, GST).isoformat(timespec="seconds")


def epoch(s):
    return dt.datetime.fromisoformat(s).timestamp()


def git(*a, inp=None):
    return subprocess.run(["git", *a], input=inp, capture_output=True, text=True).stdout.strip()


def load_state():
    git("fetch", "-q", "origin", "live")
    raw = git("show", "FETCH_HEAD:live.json")
    try:
        return json.loads(raw)
    except Exception:
        return {"prices": {}, "plans": {}, "events": [], "basis": {}}


def load_desk():
    git("fetch", "-q", "origin", "main")
    raw = git("show", "origin/main:data.json")
    try:
        return json.loads(raw)
    except Exception:
        return json.load(open("data.json"))


def publish(state):
    if os.environ.get("DRY"):
        open(os.environ["DRY"], "w").write(json.dumps(state, ensure_ascii=False, indent=1)); return
    body = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    blob = git("hash-object", "-w", "--stdin", inp=body)
    tree = git("mktree", inp=f"100644 blob {blob}\tlive.json\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="Tina's FX Signal Watcher", GIT_AUTHOR_EMAIL="noreply@anthropic.com",
               GIT_COMMITTER_NAME="Tina's FX Signal Watcher", GIT_COMMITTER_EMAIL="noreply@anthropic.com")
    c = subprocess.run(["git", "commit-tree", tree, "-m", "live " + state["updated"]], capture_output=True, text=True, env=env).stdout.strip()
    p = subprocess.run(["git", "push", "-q", "-f", "origin", f"{c}:refs/heads/live"], capture_output=True, text=True)
    if p.returncode:
        print("push failed:", p.stderr[-300:], file=sys.stderr)


def side_plan(x):
    return {k: x.get(k) for k in ("trigger", "stop", "t1", "t2")} | {"state": "waiting"}


def plans_from_desk(desk):
    """Current full plans (trigger + stop + t1) keyed by market|asof."""
    out = {}
    kinds = {(c.get("market"), c.get("asof")): c.get("kind") for c in desk.get("calls", [])}
    for m in desk.get("markets", []):
        s = m.get("signal") or {}
        sides = {}
        for k in ("long", "short"):
            x = s.get(k)
            if x and x.get("trigger") is not None and x.get("stop") is not None and x.get("t1") is not None:
                sides[k] = side_plan(x)
        if sides and s.get("asof"):
            key = f"{m['id']}|{s['asof']}"
            out[key] = {"market": m["id"], "name": m.get("name", m["id"]), "dp": m.get("dp", 2), "asof": s["asof"],
                        "valid_until": s.get("valid_until"), "kind": kinds.get((m["id"], s["asof"])) or "stop",
                        "hi": None, "lo": None, "cursor": 0, **sides}
    return out


def fmt(p, v):
    return f"{v:,.{p['dp']}f}"


def step(p, side, x, bar, events):
    """Advance one side of a plan through one candle (h/l already in spot terms)."""
    t, h, l = bar
    long = side == "long"
    fav, adv = (h, l) if long else (l, h)
    better = (lambda a, b: a >= b) if long else (lambda a, b: a <= b)  # a has reached target b
    worse = (lambda a, b: a <= b) if long else (lambda a, b: a >= b)   # a has reached stop b
    name = f"{p['name']} {'buy' if long else 'sell'}"

    def ev(kind, price, text):
        x["state"] = kind
        x[kind + "_at"] = iso(t)
        events.insert(0, {"t": iso(t), "market": p["market"], "side": side, "kind": kind, "price": price, "text": text, "plan": p["asof"]})

    if x["state"] == "waiting":
        if p["kind"] == "limit":
            filled = worse(adv, x["trigger"])          # traded back to the limit
        else:
            filled = better(fav, x["trigger"])         # broke through the trigger
        if not filled:
            return
        ev("filled", x["trigger"], f"{name} filled at {fmt(p, x['trigger'])}")
        if worse(adv, x["stop"]):
            ev("stopped", x["stop"], f"{name} stopped at {fmt(p, x['stop'])} (−1R)")
            x["r"] = -1
        return
    if x["state"] == "filled":
        risk = abs(x["trigger"] - x["stop"])
        if worse(adv, x["stop"]):
            ev("stopped", x["stop"], f"{name} stopped at {fmt(p, x['stop'])} (−1R)")
            x["r"] = -1
        elif better(fav, x["t1"]):
            x["r"] = round(abs(x["t1"] - x["trigger"]) / risk, 2) if risk else 0
            ev("t1", x["t1"], f"{name} hit target 1 at {fmt(p, x['t1'])} (+{x['r']}R). Desk method: bank half, stop to entry")
        return
    if x["state"] == "t1":
        if x.get("t2") is not None and better(fav, x["t2"]):
            risk = abs(x["trigger"] - x["stop"])
            r2 = abs(x["t2"] - x["trigger"]) / risk if risk else 0
            x["r2"] = round(r2, 2)
            ev("t2", x["t2"], f"{name} hit target 2 at {fmt(p, x['t2'])} (+{x['r2']}R)")
        elif worse(adv, x["trigger"]):
            ev("be", x["trigger"], f"{name}: runner closed at entry {fmt(p, x['trigger'])} after target 1")


def run(minutes):
    state = load_state()
    state.setdefault("basis", {})
    end = time.time() + minutes * 60
    desk, desk_at = None, 0
    while True:
        loop_start = time.time()
        if time.time() - desk_at > 300 or desk is None:
            desk, desk_at = load_desk(), time.time()
            for k, v in plans_from_desk(desk).items():
                state["plans"].setdefault(k, v)
                cur = state["plans"][k]
                cur["valid_until"] = v.get("valid_until")
                cur["current"] = True
            current = set(plans_from_desk(desk))
            for k, v in state["plans"].items():
                v["current"] = k in current
        events = state.setdefault("events", [])
        for mid, sym in SYM.items():
            try:
                meta, bars = chart(sym)
            except Exception as e:
                print(mid, "chart error", e, file=sys.stderr)
                continue
            fut = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
            ts = meta.get("regularMarketTime") or int(time.time())
            price, src, basis = fut, "Yahoo Finance", 0.0
            if mid in SPOT:
                try:
                    j = get("https://api.gold-api.com/price/" + SPOT[mid])
                    spot = float(j["price"])
                    if fut and abs(time.time() - ts) < 900:
                        state["basis"][mid] = round(fut - spot, 3)
                    basis = state["basis"].get(mid, 0.0)
                    price, src = spot, "gold-api.com spot"
                    ts = int(time.time())
                except Exception as e:
                    basis = state["basis"].get(mid, 0.0)
                    price = fut - basis if fut else None
                    src = "Yahoo futures, spot-adjusted"
            if price is None:
                continue
            chg = round((fut - prev) / prev * 100, 2) if fut and prev else None
            state["prices"][mid] = {"price": round(price, 5), "chg": chg, "asof": iso(ts), "src": src}
            # walk candles through this market's plans
            for key, p in state["plans"].items():
                if p["market"] != mid:
                    continue
                sides = [s for s in ("long", "short") if s in p and p[s]["state"] not in TERMINAL]
                if not sides:
                    continue
                start = epoch(p["asof"])
                use = bars
                if (not bars or bars[0][0] > max(start, p["cursor"])) and p["cursor"] < time.time() - 60:
                    try:
                        _, older = chart(sym, "5m", "5d")
                        use = [b for b in older if b[0] < (bars[0][0] if bars else 1e12)] + bars
                    except Exception:
                        pass
                for (t, h, l, c) in use:
                    if t < start or t <= p["cursor"] or t > time.time() - 75:
                        continue  # skip already-seen and still-forming candles
                    h, l = h - basis, l - basis
                    p["hi"] = h if p["hi"] is None else max(p["hi"], h)
                    p["lo"] = l if p["lo"] is None else min(p["lo"], l)
                    for s in sides:
                        step(p, s, p[s], (t, h, l), events)
                    p["cursor"] = t
                # expiry for sides never filled
                vu = p.get("valid_until")
                if vu and time.time() > epoch(vu):
                    for s in ("long", "short"):
                        if s in p and p[s]["state"] == "waiting":
                            p[s]["state"] = "expired"
                            p[s]["expired_at"] = vu
                            events.insert(0, {"t": vu, "market": mid, "side": s, "kind": "expired", "price": None,
                                              "text": f"{p['name']} {'buy' if s == 'long' else 'sell'} expired unfilled", "plan": p["asof"]})
        # prune: drop finished, non-current plans older than 3 days
        now = time.time()
        state["plans"] = {k: v for k, v in state["plans"].items()
                          if v.get("current") or now - epoch(v["asof"]) < 3 * 86400
                          or any(s in v and v[s]["state"] not in TERMINAL for s in ("long", "short"))}
        state["events"] = events[:150]
        state["updated"] = iso(int(now))
        publish(state)
        if time.time() + 60 > end:
            break
        time.sleep(max(5, 60 - (time.time() - loop_start)))


if __name__ == "__main__":
    mins = float(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 1
    run(mins)
