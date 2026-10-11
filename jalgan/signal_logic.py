from datetime import timedelta


def get_previous_return(df_logs, current_dt, minutes):
    previous = df_logs[
        df_logs["dt"] <= current_dt - timedelta(minutes=minutes)
    ].tail(1)

    if previous.empty:
        return None

    return (
        (df_logs.loc[df_logs.index[-1], "price"] - previous.iloc[0]["price"])
        / previous.iloc[0]["price"]
        * 100
    )


def get_previous_return_from_row(df_logs, curr, minutes):
    previous = df_logs[
        df_logs["dt"] <= curr["dt"] - timedelta(minutes=minutes)
    ].tail(1)

    if previous.empty:
        return None

    return (
        (curr["price"] - previous.iloc[0]["price"])
        / previous.iloc[0]["price"]
        * 100
    )


def calculate_market_context(df_logs, curr, config):
    context = {
        "previous_2h_return": None,
        "previous_4h_return": None,
        "previous_30m_return": None
    }

    if config.ENABLE_PREVIOUS_2H_4H:
        context["previous_2h_return"] = get_previous_return_from_row(df_logs, curr, 120)
        context["previous_4h_return"] = get_previous_return_from_row(df_logs, curr, 240)

    if config.ENABLE_PREVIOUS_30M:
        context["previous_30m_return"] = get_previous_return_from_row(df_logs, curr, 30)

    return context


def basic_filters(curr, config):
    return (
        curr["vol_xmed"] >= config.VOLUME_XMED_MIN
        and curr["volume"] >= config.VOLUME_MIN
        and curr["doi_xmed"] <= config.OI_XMED_MAX
    )


def current_market_state(curr, config):
    return (
        basic_filters(curr, config)
        and curr["dOI"] >= config.CURRENT_DOI_MIN
        and curr["vol_xmed"] >= config.CURRENT_VOLUME_XMED_MIN
    )


def generate_signal(curr, context, current_state, config):
    if not current_state:
        return None

    if config.ENABLE_PREVIOUS_2H_4H:
        if context["previous_4h_return"] is None:
            return None
        if context["previous_4h_return"] > config.PREVIOUS_4H_RETURN_MAX:
            return None
        if context["previous_2h_return"] is None:
            return None
        if context["previous_2h_return"] < config.PREVIOUS_2H_RETURN_MIN:
            return None

    if config.ENABLE_PREVIOUS_30M:
        if context["previous_30m_return"] is None:
            return None
        if context["previous_30m_return"] > config.PREVIOUS_30M_RETURN_MAX:
            return None

    if curr["taker_buy"] > config.TAKER_BUY_MAX:
        return None

    return "LONG"
