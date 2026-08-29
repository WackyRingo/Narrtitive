# Narrative Tracker

Watches DexScreener's public feeds for brand-new tokens that are
already trading harder than their age would suggest, alerts on them,
then checks back in later to record what actually happened — an
honest track record instead of a one-off claim. Entirely free to run —
no API keys required anywhere, no signup, no cost.

Rug filtering and wallet tracking are still separate modules to add later.

## What an alert looks like

```
🔔 UNUSUAL ACTIVITY
$SYMBOL — Token Name
bsc | 0.4h old

Stats
├ Price     0.00046  (+1196% 1h, +1196% 24h)
├ MCap      $462,769
├ Volume    $3,129,578 (24h)
├ Liquidity $71,014
└ Txns 1h   B 13249  S 11181

Read
└ Volume is 44.1x liquidity — very high turnover for a pool this size;
  can mean real demand or a thin pool being pushed hard. No holder or
  rug-check data yet — treat this as a lead to check manually.

dexscreener.com/bsc/0x...
bscscan.com/token/0x...
```

...followed later by one of these, automatically, at 1h/6h/24h after
the alert:

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
3. A token has to clear **all** of these to alert:
   - On an allowed chain (`ALLOWED_CHAINS` in config.py)
   - Liquidity above `MIN_LIQUIDITY_USD`
   - Younger than `MAX_TOKEN_AGE_HOURS` (this is also what filters out
     old tokens that only just picked up a paid boost)
   - 1h price change above `MIN_PRICE_CHANGE_1H` — rejects anything
     that's actively crashing, even if volume is huge. This is checked
     on price direction specifically, not buy/sell transaction counts,
     because counts alone turned out to be an unreliable signal — a
     token can have more buys than sells and still be down badly if
     the sells are larger. Price change doesn't have that problem.
   - Then either volume at `VOLUME_TO_LIQUIDITY_RATIO`x liquidity or
     more, or buy transactions clearing `MIN_BUYS_PER_HOUR` in the last hour
4. Scores it 0-100 on raw activity strength (turnover, buy pressure,
   momentum, pool size) via `compute_activity_score()` — this is a
   snapshot of how strong the trading *looks* right now, not a
   prediction and not a safety check. A well-funded rug can score just
   as high as a real mover; it says nothing about holders or contract
   risk.
5. Once alerted, a token gets checked again at each hour mark in
   `CHECKPOINT_HOURS` (1h/6h/24h by default), and the result — how far
   price has moved since the alert — gets sent as its own message.
6. After each scan, if any alerts have reached their final checkpoint,
   a running scorecard prints: how many were up, and by how much on
   average. This is the actual answer to "does this work" — not a
   vibe, a number that updates itself.
7. Everything above prints to the console, and pushes to Telegram too
   if `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` are set. Telegram sends
   check the actual response and retry once on a rate limit, with a
   small pace-yourself delay between messages — a big batch sent
   back-to-back with no delay can get silently rate-limited, which
   would otherwise look like nothing went wrong at all.

## Turning on Telegram alerts (optional, also free)

1. Message **@BotFather** on Telegram, send `/newbot`, follow the
   prompts — it replies with a bot token.
2. Send your new bot any message, then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser — your
   chat ID is in the JSON under `result[0].message.chat.id`.
3. Running locally: copy `.env.example` to `.env` and paste both values
   in. Running on GitHub Actions: add them as repo secrets instead
   (Settings -> Secrets and variables -> Actions).

## Running it on your own computer

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python main.py
```

No `.env` file is required at all — only add one for Telegram alerts.

## Running it on GitHub Actions

Already covered if you followed the earlier setup — the workflow now
saves `tracked_tokens.json` instead of the old `seen_tokens.json`.
Just re-upload the changed files (below) the same way as before —
dragging a file with the same name as an existing one replaces it,
it's not a new problem to solve.

**Files that changed this round:** `config.py`, `chain_scanner.py`,
`alerts.py`, `main.py`, `scan_once.py`, and `.github/workflows/scan.yml`.
`requirements.txt`, `.env.example`, and `README.md` are unchanged.

## Known limitations

- DexScreener's endpoints occasionally change — check
  docs.dexscreener.com if a call starts erroring.
- The thresholds are a starting point, tuned against one real batch of
  results — not exhaustively tested. Watch the track-record line over
  the next few days and adjust `config.py` if it's consistently off.
- Real-world calibration check (independent Telegram call-tracking,
  ~20-24h after alert): 0 of 19 tracked calls were positive, -81%
  average, including two that had individually looked like genuine
  winners at the 3-4x mark before fully reversing. This looks like a
  category-level base rate for fresh, actively-pumping memecoins —
  not something a scoring tweak fixes. Checkpoints now run to 72h so
  the track record reflects the full cycle instead of an optimistic
  early snapshot.
- No rug-check is applied to matches — treat one as "worth a manual
  look," not a buy signal. High volume-to-liquidity can also mean a
  thin pool getting pumped, not just genuine demand.
- Fresh-wallet ratio, LP lock status, and holder concentration aren't
  checked here (that's the rug-filter module, still to build).
- If a batched pair lookup fails outright (rare — a network hiccup),
  any checkpoints due that cycle get marked done without data rather
  than retried, so an occasional check-in may come back empty.
- `ALLOWED_CHAINS` defaults to solana/bsc/ethereum/base. Robinhood
  Chain (Robinhood's own L2, launched July 2026) is deliberately left
  out — legitimate chain, but very new and currently almost all
  memecoin speculation. Add `"robinhood"` to the list in config.py to
  include it.

## Next pieces

- `rug_filter.py` — liquidity lock, holder concentration, honeypot check
- `wallet_tracker.py` — watch known-good wallets for early buys
