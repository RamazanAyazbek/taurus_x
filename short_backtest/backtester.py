from __future__ import annotations

from datetime import timedelta

from exit_logic import find_exit
from market_data import fetch_binance_klines_for_period
from movement_profile import calculate_movement_profile
from signal_logic import calculate_market_context, current_market_state, generate_signal
from short_signal_logic import generate_short_signal, prepare_short_features


class TaurusRealisticStrictBacktester:
    def __init__(self, config, long_config=None, short_config=None):
        self.config = config
        # Separate modules keep LONG rules and thresholds independent of SHORT.
        self.long_config = long_config if long_config is not None else config
        if short_config is None:
            import short_config as default_short_config
            short_config = default_short_config
        self.short_config = short_config

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
            "skipped_cooldown": 0,
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

    def _calculate_trade_excursions(self, df_klines, entry_price, entry_dt, exit_dt, signal_type):
        """Estimate MFE/MAE only through the exit minute; 1m OHLC cannot reveal intraminute order."""
        window = df_klines[(df_klines["dt"] > entry_dt) & (df_klines["dt"] <= exit_dt)]
        if window.empty or entry_price <= 0:
            return {"trade_MFE_pct": None, "trade_MAE_pct": None}

        high_price = float(window["high"].max())
        low_price = float(window["low"].min())
        if signal_type == "LONG":
            mfe = (high_price - entry_price) / entry_price * 100.0
            mae = (low_price - entry_price) / entry_price * 100.0
        else:
            mfe = (entry_price - low_price) / entry_price * 100.0
            mae = (entry_price - high_price) / entry_price * 100.0
        return {"trade_MFE_pct": round(mfe, 3), "trade_MAE_pct": round(mae, 3)}

    def _build_trade(
        self, curr, exit_info, signal_type, entry_price, movement_profile,
        context=None, signal_meta=None, trade_excursions=None,
    ):
        hold_minutes = int((exit_info["close_dt"] - curr["dt"]).total_seconds() / 60)
        pnl = self._calculate_pnl(entry_price, exit_info["price"], signal_type)
        fee = self._calculate_fee(exit_info["status"])
        meta = signal_meta or {}

        trade = {
            "entry_time": curr["timestamp"],
            "exit_time": exit_info["close_local"].strftime("%Y-%m-%d %H:%M"),
            "type": signal_type,
            "short_hypothesis": meta.get("short_hypothesis", ""),
            "entry_price": entry_price,
            "exit_price": exit_info["price"],
            "hold_minutes": hold_minutes,
            "net_pnl_pct": round(pnl - fee, 3),
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
            "previous_30m_return": (context or {}).get("previous_30m_return"),
            "previous_2h_return": (context or {}).get("previous_2h_return"),
            "previous_4h_return": (context or {}).get("previous_4h_return"),
            "short_term_momentum_return": (context or {}).get("short_term_momentum_return"),
            "short_return_10m_pct": meta.get("short_return_10m_pct"),
            "short_return_30m_pct": meta.get("short_return_30m_pct"),
            "short_return_60m_pct": meta.get("short_return_60m_pct"),
            "short_return_2h_pct": meta.get("short_return_2h_pct"),
            "short_return_4h_pct": meta.get("short_return_4h_pct"),
            "short_zone_position": meta.get("short_zone_position"),
            "short_zone_type": meta.get("short_zone_type", ""),
            "short_zone_low": meta.get("short_zone_low"),
            "short_zone_high": meta.get("short_zone_high"),
            "short_reported_high": meta.get("short_reported_high"),
            "short_high_delta_pct": meta.get("short_high_delta_pct"),
            "short_rejection_from_high_pct": meta.get("short_rejection_from_high_pct"),
        }
        trade.update(trade_excursions or {})
        # profile_* is a fixed post-entry market profile and may continue after the trade exits.
        trade.update(movement_profile or {})
        return trade

    def _get_long_candidate(self, curr, df_logs, state_active):
        context = calculate_market_context(df_logs, curr, self.long_config)
        market_state = current_market_state(curr, self.long_config)

        if getattr(self.config, "ENABLE_STATE_LOCK", True):
            if market_state and state_active:
                return None, context, market_state, state_active
            if not market_state:
                state_active = False

        signal = generate_signal(
            curr, context, market_state, self.long_config, df_logs=df_logs
        )
        return signal, context, market_state, state_active

    def run(self, df_logs, symbol=None):
        if df_logs.empty:
            print("Датафрейм логов пуст.")
            return

        symbol = symbol or self.config.SYMBOL
        side_mode = str(getattr(self.config, "BACKTEST_SIDE", "LONG")).strip().upper()
        if side_mode not in {"LONG", "SHORT", "BOTH"}:
            raise ValueError("BACKTEST_SIDE must be LONG, SHORT, or BOTH")
        conflict_policy = str(
            getattr(self.config, "BOTH_SIGNAL_CONFLICT_POLICY", "SKIP")
        ).upper()
        if conflict_policy not in {"SKIP", "LONG", "SHORT"}:
            raise ValueError("BOTH_SIGNAL_CONFLICT_POLICY must be SKIP, LONG, or SHORT")

        df_logs = df_logs.sort_values("dt").reset_index(drop=True)
        if side_mode in {"SHORT", "BOTH"}:
            df_logs = prepare_short_features(df_logs, self.short_config)

        last_closed_time = None
        last_short_signal_time = None
        long_state_active = False

        for _, curr in df_logs.iterrows():
            self.diagnostics["rows_seen"] += 1
            curr_dt = curr["dt"]
            if last_closed_time is not None and curr_dt <= last_closed_time:
                continue

            long_signal = None
            long_context = {}
            long_market_state = False
            if side_mode in {"LONG", "BOTH"}:
                (
                    long_signal, long_context, long_market_state, long_state_active
                ) = self._get_long_candidate(curr, df_logs, long_state_active)

            short_meta = None
            if side_mode in {"SHORT", "BOTH"}:
                short_meta = generate_short_signal(curr, self.short_config)
                if short_meta and last_short_signal_time is not None:
                    cooldown = self.short_config.SHORT_REENTRY_COOLDOWN_MINUTES
                    minutes_since = (curr_dt - last_short_signal_time).total_seconds() / 60
                    if minutes_since < cooldown:
                        self.diagnostics["skipped_cooldown"] += 1
                        short_meta = None

            signal_type = None
            context = None
            signal_meta = None
            if side_mode == "LONG":
                signal_type, context = long_signal, long_context
            elif side_mode == "SHORT":
                if short_meta:
                    signal_type, signal_meta = "SHORT", short_meta
            else:  # BOTH
                if long_signal and short_meta:
                    if conflict_policy == "SKIP":
                        continue
                    if conflict_policy == "LONG":
                        signal_type, context = long_signal, long_context
                    else:
                        signal_type, signal_meta = "SHORT", short_meta
                elif long_signal:
                    signal_type, context = long_signal, long_context
                elif short_meta:
                    signal_type, signal_meta = "SHORT", short_meta

            if not signal_type:
                continue

            self.diagnostics["signal_candidates"] += 1
            start_ms = int(curr_dt.timestamp() * 1000)
            try:
                df_klines = fetch_binance_klines_for_period(
                    symbol, start_ms, max_hold_minutes=self.max_hold_minutes
                )
            except Exception as exc:
                self.diagnostics["klines_fetch_failures"] += 1
                print(
                    f"[WARN] Не удалось загрузить 1m-свечи для {signal_type} "
                    f"{curr.get('timestamp')}: {exc}"
                )
                continue

            if df_klines.empty:
                self.diagnostics["empty_klines"] += 1
                print(f"[WARN] Нет 1m-свечей для {curr.get('timestamp')}; сделка пропущена.")
                continue

            entry_price = float(curr["price"])
            exit_info = find_exit(
                df_klines,
                entry_price,
                signal_type,
                self.tp_pct,
                self.sl_pct,
                self.max_hold_minutes,
                self.be_pct,
            )
            if exit_info is None:
                self.diagnostics["no_exit"] += 1
                print(
                    f"[WARN] Не определён выход для {signal_type} "
                    f"{curr.get('timestamp')}; проверь полноту свечей."
                )
                continue

            trade_excursions = self._calculate_trade_excursions(
                df_klines, entry_price, curr_dt, exit_info["close_dt"], signal_type
            )
            movement_profile = {}
            if getattr(self.config, "ENABLE_MOVEMENT_PROFILE", True):
                movement_profile = calculate_movement_profile(
                    df_klines,
                    entry_price,
                    curr_dt,
                    signal_type,
                    getattr(self.config, "PROFILE_HORIZONS", (10, 30, 60, 120, 240, 1080)),
                )

            self.trades.append(
                self._build_trade(
                    curr, exit_info, signal_type, entry_price, movement_profile,
                    context=context, signal_meta=signal_meta,
                    trade_excursions=trade_excursions,
                )
            )
            last_closed_time = exit_info["close_dt"]
            if signal_type == "SHORT":
                last_short_signal_time = curr_dt
            elif signal_type == "LONG":
                # Preserve the historical V5 state-lock behavior for LONG entries.
                long_state_active = True

        return self.trades
