from datetime import timedelta


def previous_return(df, curr, minutes):
    """Return percent price move over the requested lookback using only past log rows."""
    cutoff = curr["dt"] - timedelta(minutes=minutes)
    # The log is sorted by time. searchsorted keeps each lookup inexpensive.
    idx = int(df["dt"].searchsorted(cutoff, side="right")) - 1
    if idx < 0:
        return None
    previous_price = float(df.iloc[idx]["price"])
    if previous_price <= 0:
        return None
    return (float(curr["price"]) - previous_price) / previous_price * 100.0


def market_context(df, curr):
    return {
        "ret_30m": previous_return(df, curr, 30),
        "ret_2h": previous_return(df, curr, 120),
        "ret_4h": previous_return(df, curr, 240),
        "ret_6h": previous_return(df, curr, 360),
        "ret_12h": previous_return(df, curr, 720),
        "ret_24h": previous_return(df, curr, 1440),
    }


def short_market_state(curr, config):
    return (
        curr["vol_xmed"] >= config.MIN_VOLUME_XMED
        and config.MIN_DOI_XMED <= curr["doi_xmed"] <= config.MAX_DOI_XMED
        and curr["dOI"] >= config.MIN_D_OI
    )


def signal_rejection_reason(curr, ctx, config):
    """Return the reason a SHORT signal is rejected, or None if it qualifies."""
    if not short_market_state(curr, config):
        return "base_filter"
    if curr["taker_buy"] > config.MAX_TAKER_BUY:
        return "base_filter"
    if curr["dPrice"] > config.MAX_CURRENT_DPRICE:
        return "base_filter"
    if ctx["ret_30m"] is None or ctx["ret_30m"] > config.MAX_PREVIOUS_30M_RETURN:
        return "base_filter"
    if ctx["ret_2h"] is None or ctx["ret_2h"] > config.MAX_PREVIOUS_2H_RETURN:
        return "base_filter"
    if ctx["ret_4h"] is None or ctx["ret_4h"] > config.MAX_PREVIOUS_4H_RETURN:
        return "base_filter"

    # Higher-timeframe direction overrides a local bearish pullback.
    # This deliberately trades fewer signals to avoid shorting a broad bull run.
    if (
        config.BULL_FILTER_ENABLED
        and ctx["ret_12h"] is not None
        and ctx["ret_24h"] is not None
        and ctx["ret_12h"] >= config.BULL_12H_RETURN_MIN
        and ctx["ret_24h"] >= config.BULL_24H_RETURN_MIN
    ):
        return "bull_market"

    # Reject an exhaustion/climax setup: unusually high volume combined with
    # an already sharp 30-minute drop and a large current-hour decline.
    if (
        config.CLIMAX_FILTER_ENABLED
        and ctx["ret_30m"] is not None
        and curr["vol_xmed"] >= config.CLIMAX_MIN_VOLUME_XMED
        and ctx["ret_30m"] <= config.CLIMAX_MAX_30M_RETURN
        and curr["dPrice"] <= config.CLIMAX_MAX_CURRENT_DPRICE
    ):
        return "sell_climax"

    return None


def short_signal(curr, ctx, config):
    return signal_rejection_reason(curr, ctx, config) is None
