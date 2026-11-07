from market_data import fetch_binance_klines_for_period
from exit_logic import find_exit
from signal_logic import market_context, signal_rejection_reason, short_market_state

class TaurusShortBacktester:
    def __init__(self, config):
        self.config = config
        self.trades = []
        self.filter_counts = {
            "bull_market": 0,
            "sell_climax": 0,
            "confirmation_bounce": 0,
            "confirmation_gap": 0,
            "confirmation_taker_buy": 0,
            "confirmation_taker_buy_max": 0,
            "confirmation_direction": 0,
        }

    def _pnl(self, entry, exit_price):
        return (entry - exit_price) / entry * 100.0

    def _fee(self, status):
        if not self.config.ENABLE_FEES:
            return 0.0
        if status == "TIMEOUT":
            return self.config.TAKER_FEE * 2
        return self.config.TAKER_FEE + (
            self.config.MAKER_FEE if status == "WIN" else self.config.TAKER_FEE
        )

    @staticmethod
    def _excursion_stats(candles, entry_dt, close_dt, entry_price):
        """MFE/MAE diagnostics from the same 1m candles; do not affect exits."""
        path = candles[(candles["dt"] > entry_dt) & (candles["dt"] <= close_dt)]
        if path.empty or entry_price <= 0:
            return {
                "mfe_pct": None, "mae_pct": None,
                "mfe_time_min": None, "mae_time_min": None,
            }
        min_low_idx = path["low"].idxmin()
        max_high_idx = path["high"].idxmax()
        min_low = float(path.loc[min_low_idx, "low"])
        max_high = float(path.loc[max_high_idx, "high"])
        return {
            "mfe_pct": round((entry_price - min_low) / entry_price * 100.0, 3),
            "mae_pct": round((entry_price - max_high) / entry_price * 100.0, 3),
            "mfe_time_min": int((path.loc[min_low_idx, "dt"] - entry_dt).total_seconds() / 60),
            "mae_time_min": int((path.loc[max_high_idx, "dt"] - entry_dt).total_seconds() / 60),
        }

    def run(self, df):
        last_closed_time = None
        state_active = False

        # One strategy pass only. Confirmation uses the next monitoring record,
        # and the actual simulated entry timestamp/price is that next record.
        for i in range(len(df)):
            curr = df.iloc[i]

            if last_closed_time is not None and curr["dt"] <= last_closed_time:
                continue

            market_state = short_market_state(curr, self.config)
            if self.config.ENABLE_STATE_LOCK:
                if market_state and state_active:
                    continue
                if not market_state:
                    state_active = False

            ctx = market_context(df, curr)
            rejection = signal_rejection_reason(curr, ctx, self.config)
            if rejection is not None:
                if rejection in self.filter_counts:
                    self.filter_counts[rejection] += 1
                continue

            entry_record = curr
            signal_time = curr["timestamp"]
            confirmation_delay = 0.0
            confirmation_move_pct = 0.0

            if self.config.ENTRY_CONFIRMATION_ENABLED:
                if i + 1 >= len(df):
                    self.filter_counts["confirmation_gap"] += 1
                    continue

                confirmation = df.iloc[i + 1]
                confirmation_delay = (
                    confirmation["dt"] - curr["dt"]
                ).total_seconds() / 60.0
                if (
                    confirmation_delay <= 0
                    or confirmation_delay > self.config.CONFIRMATION_MAX_GAP_MINUTES
                ):
                    self.filter_counts["confirmation_gap"] += 1
                    continue

                confirmation_move_pct = (
                    float(confirmation["price"]) / float(curr["price"]) - 1.0
                ) * 100.0

                # Normalize the rebound threshold to a 10-minute observation.
                # The log occasionally skips a timestamp at an hour boundary.
                threshold = (
                    self.config.CONFIRMATION_MAX_REBOUND_PCT
                    * confirmation_delay / 10.0
                )
                # An upward move is adverse to SHORT. Cancel instead of
                # retroactively entering at the earlier signal price.
                if confirmation_move_pct >= threshold:
                    self.filter_counts["confirmation_bounce"] += 1
                    continue

                # v4: apply a second, independent confirmation check. The value
                # comes from the actual next monitoring record, before entry,
                # so this does not use future candles or later trade outcomes.
                if float(confirmation["taker_buy"]) < self.config.CONFIRMATION_MIN_TAKER_BUY:
                    self.filter_counts["confirmation_taker_buy"] += 1
                    continue

                # Optional experiment A: avoid SHORT entries when aggressive
                # buying at confirmation is too strong. Kept independently
                # switchable so baseline results remain reproducible.
                if (
                    getattr(self.config, "CONFIRMATION_MAX_TAKER_BUY_ENABLED", False)
                    and float(confirmation["taker_buy"]) > self.config.CONFIRMATION_MAX_TAKER_BUY
                ):
                    self.filter_counts["confirmation_taker_buy_max"] += 1
                    continue

                # Optional experiment B: require price to resume falling
                # before entering. Positive confirmation_move_pct means the
                # price rose against SHORT; this condition blocks that case.
                if getattr(self.config, "CONFIRMATION_REQUIRE_DOWN_MOVE_ENABLED", False):
                    min_down = float(self.config.CONFIRMATION_MIN_DOWN_MOVE_PCT)
                    if confirmation_move_pct > -min_down:
                        self.filter_counts["confirmation_direction"] += 1
                        continue

                entry_record = confirmation

            start_ms = int(entry_record["dt"].timestamp() * 1000)
            try:
                candles = fetch_binance_klines_for_period(
                    self.config.SYMBOL, start_ms, self.config.TIMEOUT_MINUTES
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Binance 1m data fetch failed at {entry_record['timestamp']}: {exc}"
                ) from exc
            if candles.empty:
                continue

            entry = float(entry_record["price"])
            exit_info = find_exit(
                candles, entry, "SHORT", self.config.TP_PCT,
                self.config.SL_PCT, self.config.TIMEOUT_MINUTES
            )
            if exit_info is None:
                continue

            hold = int((exit_info["close_dt"] - entry_record["dt"]).total_seconds() / 60)
            gross = self._pnl(entry, float(exit_info["price"]))
            fee = self._fee(exit_info["status"])
            excursion = self._excursion_stats(
                candles, entry_record["dt"], exit_info["close_dt"], entry
            )
            self.trades.append({
                "signal_time": signal_time,
                "entry_time": entry_record["timestamp"],
                "exit_time": exit_info["close_local"].strftime("%Y-%m-%d %H:%M"),
                "type": "SHORT",
                "entry_price": entry,
                "exit_price": exit_info["price"],
                "hold_minutes": hold,
                "net_pnl_pct": round(gross - fee, 2),
                # Internal state is used for summary/winrate; not exported.
                "result": exit_info["status"],
                "exit_reason": exit_info["reason"],
                # Diagnostics stay in the same result CSV and do not alter exits.
                **excursion,
                "confirmation_delay_min": round(confirmation_delay, 1),
                "confirmation_move_pct": round(confirmation_move_pct, 3),
                "entry_dOI": entry_record["dOI"],
                "entry_dPrice": entry_record["dPrice"],
                "entry_volume": entry_record["volume"],
                "entry_taker_buy": entry_record["taker_buy"],
                "entry_zone": entry_record["in_zone"],
            })
            last_closed_time = exit_info["close_dt"]
            state_active = True

        print("Фильтры SHORT:")
        print(f"  Пропущено: бычий тренд 12h/24h : {self.filter_counts['bull_market']}")
        print(f"  Пропущено: истощённое падение     : {self.filter_counts['sell_climax']}")
        print(f"  Пропущено: отскок на подтверждении: {self.filter_counts['confirmation_bounce']}")
        print(f"  Пропущено: TakerBuy на подтверждении < {self.config.CONFIRMATION_MIN_TAKER_BUY:g}%: {self.filter_counts['confirmation_taker_buy']}")
        if getattr(self.config, "CONFIRMATION_MAX_TAKER_BUY_ENABLED", False):
            print(f"  Пропущено: TakerBuy на подтверждении > {self.config.CONFIRMATION_MAX_TAKER_BUY:g}%: {self.filter_counts['confirmation_taker_buy_max']}")
        if getattr(self.config, "CONFIRMATION_REQUIRE_DOWN_MOVE_ENABLED", False):
            print(f"  Пропущено: нет возобновления падения (минимум {self.config.CONFIRMATION_MIN_DOWN_MOVE_PCT:g}%): {self.filter_counts['confirmation_direction']}")
        print(f"  Пропущено: нет корректной записи подтверждения: {self.filter_counts['confirmation_gap']}")
