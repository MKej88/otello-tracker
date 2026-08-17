# Euronext delayed OTEC price source

Phase 11 adds an automated official OTEC price input from Euronext's public delayed Oslo equity trade files.

## Source contract

- File type: `EQUITIES`
- Trading location: `OSL`
- Primary time selection: `CURRENT_TRADING_DAY`
- Fallback time selection: `PREVIOUS_TRADING_DAY`
- Instrument validation: ISIN `NO0010040611`, venue `XOSL`, NOK price

The adapter locates the real CSV header dynamically, filters strictly for OTEC, parses prices with `Decimal`, and selects the latest valid trade deterministically using source timestamps and trade identity.

## Price semantics and priority

The delayed feed represents the latest observed trade and is stored as `LAST`, not mislabeled as an official close. A same-day official Euronext `CLOSE` remains stronger than `LAST`, while an official same-day Euronext `LAST` is stronger than the manual Investing fallback.

If the current-trading-day file contains no valid OTEC trade, the adapter may use the previous-trading-day file. Explicit historical target-date refreshes do not call the live-only delayed source.

## Failure behavior

Source/network/schema failures are fail-soft. They are recorded in `source_errors`; existing validated OTEC prices are not overwritten by fabricated or weaker data.

Temporary discovery workflows used during implementation are intentionally excluded from the final branch.