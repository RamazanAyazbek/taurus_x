"""Causal experimental features: monitoring data no later than confirmation.

No support or taker feature uses a later monitor observation, future TP/SL,
market outcome, or any Binance candle from after the simulated entry.
"""
from datetime import timedelta
import math
import re

_S1 = re.compile(r"(?:^|\s)S1\[\s*(\d+(?:\.\d+)?)k\s*-\s*(\d+(?:\.\d+)?)k\s*\]", re.IGNORECASE)


def _as_float(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def parse_s1_band(zone_text):
    """S1[75.2k-75.4k] -> (75200.0, 75400.0). No inferred levels."""
    match = _S1.search(str(zone_text))
    if not match:
        return None
    lower, upper = float(match.group(1)) * 1000, float(match.group(2)) * 1000
    if lower <= 0 or upper <= lower:
        return None
    return lower, upper


def support_proximity(df, entry_index, confirmation_price, settings):
    """Nearest recent *observed* S1 at or before confirmation.

    Finds the last zone that is still at/below the entry price. A zone
    completely above the price is a broken support and not treated as support.
    `NONE` means unknown (not 'no support').
    """
    entry = df.iloc[entry_index]
    at = entry['dt']
    cutoff = at - timedelta(minutes=settings.SUPPORT_LOOKBACK_MINUTES)
    best = None
    for i in range(entry_index, -1, -1):
        older = df.iloc[i]
        if older['dt'] < cutoff:
            break
        band = parse_s1_band(older.get('in_zone', ''))
        if band is None:
            continue
        lo, hi = band
        if confirmation_price < lo:
            continue  # Band has been lost; do not call it support below us.
        distance_pct = max(0., (confirmation_price - hi) / confirmation_price * 100.)
        best = {
            'support_low': lo,
            'support_high': hi,
            'support_distance_pct': round(distance_pct, 4),
            'support_observed_at': older['timestamp'],
            'support_near': distance_pct <= settings.SUPPORT_NEAR_PCT,
        }
        break  # Most recent usable S1
    return best or {
        'support_low': None,
        'support_high': None,
        'support_distance_pct': None,
        'support_observed_at': '',
        'support_near': False,
    }


def taker_buy_change(df, entry_index, settings):
    """Confirmation minus past 20-minute monitor reading, max 10m staleness."""
    curr = df.iloc[entry_index]
    target = curr['dt'] - timedelta(minutes=settings.TAKER_LOOKBACK_MINUTES)
    # Can read the current row's history only, never the future rows.
    old_index = int(df['dt'].searchsorted(target, side='right')) - 1
    result = {
        'taker_buy_lookback': None, 'taker_buy_delta_pp': None,
        'taker_buy_rising_fast': False, 'taker_buy_lookback_time': ''
    }
    if old_index < 0:
        return result
    old = df.iloc[old_index]
    age_minutes = (target - old['dt']).total_seconds() / 60.0
    if age_minutes < 0 or age_minutes > settings.TAKER_LOOKBACK_MAX_STALENESS_MINUTES:
        return result
    old_buy = _as_float(old['taker_buy'])
    now_buy = _as_float(curr['taker_buy'])
    if old_buy is None or now_buy is None:
        return result
    diff = now_buy - old_buy
    return {
        'taker_buy_lookback': round(old_buy, 3),
        'taker_buy_delta_pp': round(diff, 3),
        'taker_buy_rising_fast': diff >= settings.TAKER_RISE_THRESHOLD_PP,
        'taker_buy_lookback_time': old['timestamp'],
    }


def select_delayed_entry(candles, confirmation_dt, confirmation_price, settings):
    """A hypothetical fill at the 1m OPEN exactly delay minutes later.

    If that minute is missing, it is an unavailable experiment (no forward fill).
    It is intentionally NOT the end-of-minute close, which would look ahead.
    """
    target_dt = confirmation_dt + timedelta(minutes=settings.PREENTRY_DELAY_MINUTES)
    matching = candles[candles['dt'] == target_dt]
    if matching.empty or 'open' not in candles:
        return None
    entry = _as_float(matching.iloc[0]['open'])
    if entry is None or entry <= 0:
        return None
    move = (entry / confirmation_price - 1.0) * 100.0
    return {
        'entry_dt': target_dt,
        'entry_price': entry,
        'preentry_move_pct': round(move, 4),
        'preentry_fell_fast': move <= -settings.PREENTRY_FALL_THRESHOLD_PCT,
    }
