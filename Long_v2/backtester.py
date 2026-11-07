from __future__ import annotations

from exit_logic import find_exit
from market_data import fetch_binance_klines_for_period
from movement_profile import calculate_movement_profile
from signal_logic import (
    calculate_market_context,
    current_market_state,
    generate_signal,
    prepare_long_features,
)


class TaurusRealisticStrictBacktester:
    def __init__(self, config):
        self.config = config
        self.tp_pct = config.TP_PCT
        self.sl_pct = config.SL_PCT
        self.be_pct = config.BE_PCT
        self.taker_fee = config.TAKER_FEE
        self.maker_fee = config.MAKER_FEE
        self.max_hold_minutes = config.TIMEOUT_MINUTES
        self.trades = []
        self.diagnostics = {
            "rows_seen": 0,
            "signal_candidates": 0,
            "klines_fetch_failures": 0,
            "empty_klines": 0,
            "no_exit": 0,
        }

    def _calculate_pnl(self, entry_price, exit_price, signal_type):
        if signal_type == "LONG":
            return (exit_price - entry_price) / entry_price * 100
        return (entry_price - exit_price) / entry_price * 100

    def _calculate_fee(self, exit_status):
        if not self.config.ENABLE_FEES:
            return 0.0
        if exit_status == "TIMEOUT":
            return self.taker_fee * 2
        return self.taker_fee + (self.maker_fee if exit_status == "WIN" else self.taker_fee)

    def _build_trade(self, curr, exit_info, signal_type, entry_price, movement_profile, context):
        hold_minutes = int((exit_info["close_dt"] - curr["dt"]).total_seconds() / 60)
        pnl = self._calculate_pnl(entry_price, exit_info["price"], signal_type)
        fee = self._calculate_fee(exit_info["status"])

        return {
            "entry_time": curr["timestamp"],
            "exit_time": exit_info["close_local"].strftime("%Y-%m-%d %H:%M"),
            "type": signal_type,
            "entry_price": entry_price,
            "exit_price": exit_info["price"],
            "hold_minutes": hold_minutes,
            "net_pnl_pct": round(pnl - fee, 2),
            "gross_price_return_pct": round(pnl, 3),
            "fees_pct": round(fee, 3),
            "result": exit_info["status"],
            "exit_reason": exit_info["reason"],
            "entry_dOI": curr.get("dOI"),
            "entry_dPrice": curr.get("dPrice"),
            "entry_volume": curr.get("volume"),
            "entry_taker_buy": curr.get("taker_buy"),
            "entry_zone": curr.get("in_zone", "NONE"),
            "entry_vol_xmed": curr.get("vol_xmed"),
            "entry_doi_xmed": curr.get("doi_xmed"),
            "previous_30m_return": context.get("previous_30m_return"),
            "previous_2h_return": context.get("previous_2h_return"),
            "previous_4h_return": context.get("previous_4h_return"),
            "previous_12h_return": context.get("previous_12h_return"),
            "previous_48h_return": context.get("previous_48h_return"),
            "long_sma_12h_slope_2h_pct": context.get("long_sma_12h_slope_2h_pct"),
            "long_price_vs_sma_12h_pct": context.get("long_price_vs_sma_12h_pct"),
            **(movement_profile or {}),
        }

    def run(self, df_logs, symbol=None):
        if df_logs.empty:
            print("Датафрейм логов пуст.")
            return self.trades

        symbol = symbol or self.config.SYMBOL
        df_logs = prepare_long_features(df_logs, self.config)
        last_closed_time = None
        state_active = False

        for _, curr in df_logs.iterrows():
            self.diagnostics["rows_seen"] += 1
            curr_dt = curr["dt"]
            if last_closed_time is not None and curr_dt <= last_closed_time:
                continue

            context = calculate_market_context(df_logs, curr, self.config)
            market_state = current_market_state(curr, self.config)

            if self.config.ENABLE_STATE_LOCK:
                if market_state and state_active:
                    continue
                if not market_state:
                    state_active = False

            signal_type = generate_signal(curr, context, market_state, self.config)
            if not signal_type:
                continue

            self.diagnostics["signal_candidates"] += 1
            start_ms = int(curr_dt.timestamp() * 1000)
            try:
                # Critical speed fix: fetch only the 18h holding window, not all candles to now.
                df_klines = fetch_binance_klines_for_period(
                    symbol,
                    start_ms,
                    max_hold_minutes=self.max_hold_minutes,
                )
            except Exception as exc:
                self.diagnostics["klines_fetch_failures"] += 1
                print(
                    f"[WARN] Не удалось загрузить 1m-свечи для {curr.get('timestamp')}: {exc}"
                )
                continue

            if df_klines.empty:
                self.diagnostics["empty_klines"] += 1
                print(f"[WARN] Нет 1m-свечей для {curr.get('timestamp')}; сделка пропущена.")
                continue

            entry_price = float(curr["price"])
            use_be = self.be_pct if getattr(self.config, "ENABLE_BREAKEVEN", False) else None
            exit_info = find_exit(
                df_klines,
                entry_price,
                signal_type,
                self.tp_pct,
                self.sl_pct,
                self.max_hold_minutes,
                be_pct=use_be,
            )
            if exit_info is None:
                self.diagnostics["no_exit"] += 1
                print(
                    f"[WARN] Не определён выход для {signal_type} {curr.get('timestamp')}; "
                    "проверь полноту минутных свечей."
                )
                continue

            movement_profile = {}
            if self.config.ENABLE_MOVEMENT_PROFILE:
                movement_profile = calculate_movement_profile(
                    df_klines,
                    entry_price,
                    curr_dt,
                    signal_type,
                    self.config.PROFILE_HORIZONS,
                )

            self.trades.append(
                self._build_trade(
                    curr, exit_info, signal_type, entry_price, movement_profile, context
                )
            )
            last_closed_time = exit_info["close_dt"]
            state_active = True

        print(
            "[DIAGNOSTICS] rows={rows_seen}; candidates={signal_candidates}; "
            "fetch_failures={klines_fetch_failures}; empty_klines={empty_klines}; "
            "no_exit={no_exit}".format(**self.diagnostics)
        )
        return self.trades
