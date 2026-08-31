# Narrative Tracker

Watches DexScreener's public feeds for brand-new tokens that are
already trading harder than their age would suggest, alerts on them,
checks Solana tokens for rug/bundle/sniper/insider risk, then checks
back in later to record what actually happened — an honest track
record instead of a one-off claim. Free to run — no keys required for
the core scanner; two optional free-tier keys unlock Telegram push and
the Solana risk check.

Wallet tracking is still a separate module to add later.

## What an alert looks like

```
🔔 UNUSUAL ACTIVITY
$SYMBOL — Token Name
solana | 0.4h old | Activity: 79/100 (Strong)

Stats
├ Price     0.00046  (+1196% 1h, +1196% 24h)
├ MCap      $462,769
├ Volume    $3,129,578 (24h)
├ Liquidity $71,014
└ Txns 1h   B 13249  S 11181

Security
└ Risk 3/10 · Snipers 4% · Bundlers 8% · Insiders 1%

Read
└ Volume is 44.1x liquidity — very high turnover for a pool this size;
  can mean real demand or a thin pool being pushed hard.

dexscreener.com/solana/...
solscan.io/token/...
app.bubblemaps.io/sol/token/...
```

...followed later by one of these, automatically, at 1h/6h/24h/72h
after the alert:

```
📍 24H CHECK-IN
$SYMBOL — Token Name
Since alert: +180%
MCap now: $1,296,000
```

## How it works

1. Polls `/token-profiles/latest/v1` and `/token-boosts/latest/v1`
   (free, no key) for tokens DexScreener has newly indexed, and adds
   any not seen before to a local watch list (`tracked_tokens.json`).
2. Every cycle, re-checks everything still on that watch list (batched,
   up to 30 addresses per call) and fires an alert on anything that now
   clears the bar — this catches tokens that build momentum after
   their first pass, not just ones that qualify immediately.
3. A token has to clear **all** of these to alert: on an allowed chain,
   liquidity above `MIN_LIQUIDITY_USD`, younger than
   `MAX_TOKEN_AGE_HOURS`, 1h price change above `MIN_PRICE_CHANGE_1H`
   (rejects anything actively crashing, checked on price direction
   specifically since buy/sell counts alone turned out unreliable —
   a token can have more buys than sells and still be down badly),
   and either volume at `VOLUME_TO_LIQUIDITY_RATIO`x liquidity or
   buy transactions clearing `MIN_BUYS_PER_HOUR`.
4. For Solana tokens, checks Solana Tracker's free risk API for a rug
   score plus sniper/bundler/insider wallet percentages — "bundled"
   supply means the deployer controls many wallets that all bought at
   launch to look like organic demand while hiding a large real
   position; that's what the bundler figure is catching.
5. Scores it 0-100 on raw activity strength (turnover, buy pressure,
   momentum, pool size) via `compute_activity_score()` — a snapshot of
   how strong the trading *looks* right now, not a prediction. A
   well-funded rug can score just as high as a real mover; step 4 is
   what actually speaks to legitimacy, on chains it covers.
6. Once alerted, a token gets checked again at each hour mark in
   `CHECKPOINT_HOURS` (1h/6h/24h/72h by default), and the result — how
   far price has moved since the alert — gets sent as its own message.
7. After each scan, if any alerts have reached their final checkpoint,
   a running scorecard prints: how many were up, and by how much on
   average.
8. Every alert links to a Bubblemaps visual holder map — click through
   to see wallet clusters at a glance, on any chain, no API needed.
9. Everything prints to the console, and pushes to Telegram too if
   `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are set. Telegram sends
   check the actual response and retry once on a rate limit, with a
   pace-yourself delay between messages — a big batch sent back-to-back
   can get silently rate-limited otherwise.

## Turning on Telegram alerts (optional, free)

1. Message **@BotFather** on Telegram, send `/newbot`, follow the
   prompts — it replies with a bot token.
2. Send your new bot any message, then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser — your
   chat ID is in the JSON under `result[0].message.chat.id`.
3. Running locally: copy `.env.example` to `.env` and paste both values
   in. Running on GitHub Actions: add them as repo secrets instead
   (Settings -> Secrets and variables -> Actions).

## Turning on the Solana risk check (optional, free)

Sign up at solanatracker.io, grab a key from the dashboard — free tier
is 2,500 requests/month, no card. Only one request per *new* alert
(not per candidate checked), so realistic usage should sit comfortably
under that. Add `SOLANA_TRACKER_API_KEY` the same way as the Telegram
values above. Solana only; BSC/ETH/Base tokens still get the Bubblemaps
link but no numeric Security line yet — that needs a second provider
(GoPlus Security looks like the candidate, not yet researched or wired in).

## Running it on your own computer

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python main.py
```

No `.env` file is required at all — only add one for Telegram and/or
the Solana risk check.

## Running it on GitHub Actions

Re-upload the changed files the same way as always — dragging a file
with the same name as an existing one replaces it, not a new problem.

**Files that changed this round:** `rug_filter.py` (new), `config.py`,
`chain_scanner.py`, `alerts.py`, `.env.example`, and
`.github/workflows/scan.yml`. `main.py`, `scan_once.py`,
`requirements.txt` are unchanged.

## Known limitations

- DexScreener's and Solana Tracker's endpoints occasionally change —
  check their docs if a call starts erroring.
- The thresholds are a starting point, tuned against real batches of
  results — not exhaustively tested. Watch the track-record line and
  adjust `config.py` if it's consistently off.
- Real-world calibration check (independent Telegram call-tracking,
  ~20-24h after alert, before the rug/bundle check existed): 0 of 19
  tracked calls were positive, -81% average, including two that had
  individually looked like genuine winners at the 3-4x mark before
  fully reversing. This looks like a category-level base rate for
  fresh, actively-pumping memecoins — not something a scoring tweak
  fixes. Worth re-checking now that rug/bundle data and the 72h
  checkpoint are both in place.
- Rug/bundle/sniper/insider data is Solana-only and requires a free
  API key — without one, or on other chains, alerts fall back to the
  Bubblemaps link with no numeric Security line. Neither is a
  guarantee either way; both are heuristic scanners, same caveat as
  everything else here — clearing every check narrows out known red
  flags, it doesn't confirm a token is safe.
- Field names in `rug_filter.py` are based on documentation and SDK
  examples, not a live test against the API — parsing is defensive
  (missing fields just don't render) rather than guessed, so a wrong
  field name degrades to "less detail shown," not a crash. If the
  whole Security block stops appearing, check field names against
  current docs.
- If a batched pair lookup fails outright (rare — a network hiccup),
  any checkpoints due that cycle get marked done without data rather
  than retried, so an occasional check-in may come back empty.
- `ALLOWED_CHAINS` defaults to solana/bsc/ethereum/base. Robinhood
  Chain (Robinhood's own L2, launched July 2026) is deliberately left
  out — legitimate chain, but very new and currently almost all
  memecoin speculation. Add `"robinhood"` to the list to include it.

## Next pieces

- GoPlus Security (or similar) for BSC/ETH/Base rug data, to match
  what Solana Tracker now covers for Solana
- `wallet_tracker.py` — watch known-good wallets for early buys
