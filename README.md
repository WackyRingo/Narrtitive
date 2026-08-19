# Narrative Tracker

Watches DexScreener's public feeds for brand-new tokens that are already
trading harder than their age would suggest, and sends a stats-block
alert with a written "Read" section underneath. Entirely free to run —
no API keys required anywhere, no signup, no cost, no optional paid
add-ons in the code.

Rug filtering and wallet tracking are still separate modules to add later.

## What an alert looks like

```
🔔 UNUSUAL ACTIVITY
$SYMBOL — Token Name
bsc | 3.2h old

Stats
├ Price     $0.00042  (+18% 1h, +340% 24h)
├ MCap      $840,000
├ Volume    $612,000 (24h)
├ Liquidity $71,000
└ Txns 1h   B 312  S 98

Read
└ Volume is 8.6x liquidity — very high turnover for a pool this size;
  can mean real demand or a thin pool being pushed hard. Buyers well
  ahead of sellers in the last hour (312 buys vs 98 sells). No holder
  or rug-check data yet — treat this as a lead to check manually.

dexscreener.com/bsc/0x...
bscscan.com/token/0x...
```

## How it works

1. Polls `/token-profiles/latest/v1` and `/token-boosts/latest/v1` (both
   free, no key, 60 req/min limit) for tokens DexScreener has newly
   indexed.
2. For any address not already seen, pulls its live pair data from
   `/latest/dex/tokens/<address>`.
3. Flags it if liquidity clears `MIN_LIQUIDITY_USD`, and either 24h
   volume is `VOLUME_TO_LIQUIDITY_RATIO`x liquidity or more, or buy
   transactions in the last hour clear `MIN_BUYS_PER_HOUR`.
4. `generate_quick_read()` in `chain_scanner.py` turns those same
   numbers into a few plain-language sentences — rule-based, no API
   call, no cost.
5. Prints the full alert, and pushes it to Telegram too if configured.

## Turning on Telegram alerts (optional, also free)

1. Message **@BotFather** on Telegram, send `/newbot`, follow the
   prompts (pick a name and username) — it replies with a bot token.
2. Send your new bot any message, then visit
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser — your
   chat ID is in the JSON under `result[0].message.chat.id`.
3. Running locally: copy `.env.example` to `.env` and paste both values
   in. Running on GitHub Actions: add them as repo secrets instead
   (Settings -> Secrets and variables -> Actions) — same names,
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

## Running it on your own computer

Requires Python 3.10+.

```bash
pip install -r requirements.txt
python main.py
```

No `.env` file is required at all — only add one if you want Telegram
alerts on top of console output. This runs in a loop and needs to stay
running; closing the terminal stops it.

## Running it without keeping your computer on

### GitHub Actions (free, recommended)

1. Push this whole folder to a **public** GitHub repo — public is what
   keeps it free (a private repo would burn through the 2,000 free
   minutes/month fast at a 10-minute schedule). Nothing in the code is
   sensitive; secrets stay in GitHub's secret store either way.
2. Add `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` as repo secrets if
   you're using Telegram (Settings -> Secrets and variables ->
   Actions) — GitHub Actions doesn't read `.env` files.
3. `.github/workflows/scan.yml` is already set up to run every 10
   minutes and commit its "seen tokens" memory back to the repo so it
   doesn't lose track between runs. Nothing else to configure.
4. Check the "Actions" tab to watch it run, or click "Run workflow"
   there to trigger one manually.

Uses `scan_once.py` instead of `main.py` — same scanner, but runs once
and exits instead of looping, since GitHub Actions starts a fresh run
each time rather than keeping a process alive.

### Railway (not free — mentioned for reference only)

Technically possible — connect the repo, set the start command to
`python main.py`, deploy as a worker. Not part of the recommended path
here though: the free trial is $5 in credit for 30 days, then the
ongoing free plan is just $1/month, which a 24/7 process burns through
fast — realistic ongoing cost is Railway's $5/month Hobby plan.
GitHub Actions above gets the same result for actually $0.

## Known limitations

- DexScreener's endpoints occasionally change — check
  docs.dexscreener.com if a call starts erroring.
- The thresholds are a starting guess — watch what comes through for a
  few days and adjust `MIN_LIQUIDITY_USD`, `VOLUME_TO_LIQUIDITY_RATIO`,
  and `MIN_BUYS_PER_HOUR` in config.py against what you actually see.
- No rug-check is applied to matches — treat one as "worth a manual
  look," not a buy signal. High volume-to-liquidity can also mean a
  thin pool getting pumped, not just genuine demand.
- Fresh-wallet ratio, LP lock status, and holder concentration aren't
  checked here (that's what Phanes' "Security" section shows) — that
  needs a chain-specific holder API, which is the rug-filter module,
  still to build, and free options for that are more limited.
- No historical ATH tracking — the "latest" feeds mostly surface each
  token once as it's newly listed, so there's no cheap way to keep
  watching it afterward yet. Stats shown are a snapshot at alert time.

## Next pieces

- `rug_filter.py` — liquidity lock, holder concentration, honeypot check
- `wallet_tracker.py` — watch known-good wallets for early buys
