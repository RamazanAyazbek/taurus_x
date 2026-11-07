import re
from datetime import timedelta

from market_data import fetch_binance_klines_for_period
from exit_logic import find_exit
from signal_logic import market_context, signal_rejection_reason, short_market_state


_S1_ZONE = re.compile(r"S1\[\s*(\d+(?:\.\d+)?)k\s*-\s*(\d+(?:\.\d+)?)k\s*\]", re.I)


class TaurusShortBacktester:
    def __init__(self, config):
        self.config = config
        self.trades = []
        self.s1_rejections = []
        self.filter_counts = {
            "bull_market": 0,
            "sell_climax": 0,
            "confirmation_bounce": 0,
            "confirmation_gap": 0,
            "confirmation_taker_buy": 0,
            "confirmation_taker_buy_max": 0,
            "confirmation_direction": 0,
            "support_near": 0,
            "support_entry_near": 0,
            "support_cooldown": 0,
            "missing_entry_candle": 0,
            "missing_exit_data": 0,
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
    def _excursion_stats(candles, entry_dt, close_dt, entry_price, include_entry_candle):
        if include_entry_candle:
            path = candles[(candles["dt"] >= entry_dt) & (candles["dt"] <= close_dt)]
        else:
            path = candles[(candles["dt"] > entry_dt) & (candles["dt"] <= close_dt)]
        if path.empty or entry_price <= 0:
            return {"mfe_pct": None, "mae_pct": None,
                    "mfe_time_min": None, "mae_time_min": None}
        min_idx = path["low"].idxmin()
        max_idx = path["high"].idxmax()
        return {
            "mfe_pct": round((entry_price - float(path.loc[min_idx, "low"])) / entry_price * 100, 3),
            "mae_pct": round((entry_price - float(path.loc[max_idx, "high"])) / entry_price * 100, 3),
            "mfe_time_min": int((path.loc[min_idx, "dt"] - entry_dt).total_seconds() / 60),
            "mae_time_min": int((path.loc[max_idx, "dt"] - entry_dt).total_seconds() / 60),
        }

    def _support_info(self, df, confirmation_index, price):
        cutoff = df.iloc[confirmation_index]["dt"] - timedelta(
            minutes=self.config.SUPPORT_LOOKBACK_MINUTES
        )
        for j in range(confirmation_index, -1, -1):
            row = df.iloc[j]
            if row["dt"] < cutoff:
                break
            match = _S1_ZONE.search(str(row.get("in_zone", "")))
            if not match:
                continue
            low, high = float(match.group(1)) * 1000, float(match.group(2)) * 1000
            if low <= 0 or high <= low or price < low:
                continue
            distance = max(0.0, (price - high) / price * 100.0)
            return {"distance_pct": distance, "zone_low": low,
                    "zone_high": high, "zone_timestamp": row["timestamp"]}
        return None

    def run(self, df):
        cfg = self.config
        source = cfg.ENTRY_PRICE_SOURCE.strip().lower()
        if source not in ("collector", "binance_open"):
            raise ValueError("ENTRY_PRICE_SOURCE должен быть 'collector' или 'binance_open'")
        if int(cfg.ENTRY_DELAY_MINUTES) < 0:
            raise ValueError("ENTRY_DELAY_MINUTES не может быть отрицательным")
        if int(cfg.SUPPORT_COOLDOWN_MINUTES) < 0:
            raise ValueError("SUPPORT_COOLDOWN_MINUTES не может быть отрицательным")
        if float(cfg.SUPPORT_NEAR_PCT) < 0:
            raise ValueError("SUPPORT_NEAR_PCT не может быть отрицательным")

        last_closed_time = None
        state_active = False
        support_block_until = None

        for i in range(len(df)):
            curr = df.iloc[i]
            if last_closed_time is not None and curr["dt"] <= last_closed_time:
                continue

            market_state = short_market_state(curr, cfg)
            if cfg.ENABLE_STATE_LOCK:
                if market_state and state_active:
                    continue
                if not market_state:
                    state_active = False

            if cfg.SUPPORT_FILTER_ENABLED and support_block_until is not None:
                if curr["dt"] < support_block_until:
                    self.filter_counts["support_cooldown"] += 1
                    continue

            ctx = market_context(df, curr)
            rejection = signal_rejection_reason(curr, ctx, cfg)
            if rejection is not None:
                if rejection in self.filter_counts:
                    self.filter_counts[rejection] += 1
                continue

            signal_time = curr["timestamp"]
            entry_record = curr
            confirmation_delay = 0.0
            confirmation_move_pct = 0.0
            confirm_idx = i

            if cfg.ENTRY_CONFIRMATION_ENABLED:
                if i + 1 >= len(df):
                    self.filter_counts["confirmation_gap"] += 1
                    continue
                confirmation = df.iloc[i + 1]
                confirmation_delay = (confirmation["dt"] - curr["dt"]).total_seconds() / 60
                if confirmation_delay <= 0 or confirmation_delay > cfg.CONFIRMATION_MAX_GAP_MINUTES:
                    self.filter_counts["confirmation_gap"] += 1
                    continue
                confirmation_move_pct = (float(confirmation["price"]) / float(curr["price"]) - 1) * 100
                threshold = cfg.CONFIRMATION_MAX_REBOUND_PCT * confirmation_delay / 10.0
                if confirmation_move_pct >= threshold:
                    self.filter_counts["confirmation_bounce"] += 1
                    continue
                if float(confirmation["taker_buy"]) < cfg.CONFIRMATION_MIN_TAKER_BUY:
                    self.filter_counts["confirmation_taker_buy"] += 1
                    continue
                if (cfg.CONFIRMATION_MAX_TAKER_BUY_ENABLED
                        and float(confirmation["taker_buy"]) > cfg.CONFIRMATION_MAX_TAKER_BUY):
                    self.filter_counts["confirmation_taker_buy_max"] += 1
                    continue
                if cfg.CONFIRMATION_REQUIRE_DOWN_MOVE_ENABLED:
                    if confirmation_move_pct > -cfg.CONFIRMATION_MIN_DOWN_MOVE_PCT:
                        self.filter_counts["confirmation_direction"] += 1
                        continue
                entry_record = confirmation
                confirm_idx = i + 1

            s1 = self._support_info(df, confirm_idx, float(entry_record["price"])) if cfg.SUPPORT_FILTER_ENABLED else None
            if s1 is not None and s1["distance_pct"] <= cfg.SUPPORT_NEAR_PCT:
                self.filter_counts["support_near"] += 1
                confirmation_dt = entry_record["dt"]
                support_block_until = confirmation_dt + timedelta(minutes=cfg.SUPPORT_COOLDOWN_MINUTES)
                item = {
                    "signal_time": signal_time,
                    "confirmation_time": entry_record["timestamp"],
                    "check_stage": "confirmation",
                    "check_time": entry_record["timestamp"],
                    "sim_entry_price": None,
                    "confirmation_price": float(entry_record["price"]),
                    "distance_to_s1_pct": round(s1["distance_pct"], 4),
                    "s1_low": s1["zone_low"],
                    "s1_high": s1["zone_high"],
                    "s1_observed_at": s1["zone_timestamp"],
                    "cooldown_until": support_block_until.tz_convert("Asia/Almaty").strftime("%Y-%m-%d %H:%M"),
                    "confirmation_taker_buy": float(entry_record["taker_buy"]),
                    "confirmation_move_pct": round(confirmation_move_pct, 4),
                }
                self.s1_rejections.append(item)
                print(f"[S1] {entry_record['timestamp'][5:]} | {s1['distance_pct']:.3f}% от S1 | "
                      f"пропуск до {item['cooldown_until'][5:]}")
                continue

            # No look-ahead: in the market-fill approximation, the entry is
            # the OPEN of the minute at confirmation + specified delay.
            if source == "binance_open":
                actual_dt = entry_record["dt"] + timedelta(minutes=int(cfg.ENTRY_DELAY_MINUTES))
                include_entry_candle = True
            else:
                actual_dt = entry_record["dt"]
                include_entry_candle = False

            start_ms = int(actual_dt.timestamp() * 1000)
            try:
                candles = fetch_binance_klines_for_period(cfg.SYMBOL, start_ms, cfg.TIMEOUT_MINUTES)
            except Exception as exc:
                raise RuntimeError(f"Binance 1m error at {entry_record['timestamp']}: {exc}") from exc
            if candles.empty or candles.iloc[0]["dt"] != actual_dt:
                self.filter_counts["missing_entry_candle"] += 1
                continue

            if source == "binance_open":
                if "open" not in candles.columns:
                    raise RuntimeError("Binance 1m candles: нет поля 'open'")
                entry = float(candles.iloc[0]["open"])
            else:
                entry = float(entry_record["price"])
            if entry <= 0:
                raise RuntimeError("Неверная цена входа: <= 0")

            # A second check of the SAME S1 condition with the price actually
            # available at our modeled Binance entry minute (no future zones).
            if (cfg.SUPPORT_FILTER_ENABLED and source == "binance_open"
                    and cfg.SUPPORT_RECHECK_AT_ENTRY):
                entry_s1 = self._support_info(df, confirm_idx, entry)
                if entry_s1 is not None and entry_s1["distance_pct"] <= cfg.SUPPORT_NEAR_PCT:
                    self.filter_counts["support_near"] += 1
                    self.filter_counts["support_entry_near"] += 1
                    support_block_until = actual_dt + timedelta(minutes=cfg.SUPPORT_COOLDOWN_MINUTES)
                    item = {
                        "signal_time": signal_time,
                        "confirmation_time": entry_record["timestamp"],
                        "check_stage": "binance_open",
                        "check_time": actual_dt.tz_convert("Asia/Almaty").strftime("%Y-%m-%d %H:%M"),
                        "confirmation_price": float(entry_record["price"]),
                        "sim_entry_price": entry,
                        "distance_to_s1_pct": round(entry_s1["distance_pct"], 4),
                        "s1_low": entry_s1["zone_low"],
                        "s1_high": entry_s1["zone_high"],
                        "s1_observed_at": entry_s1["zone_timestamp"],
                        "cooldown_until": support_block_until.tz_convert("Asia/Almaty").strftime("%Y-%m-%d %H:%M"),
                        "confirmation_taker_buy": float(entry_record["taker_buy"]),
                        "confirmation_move_pct": round(confirmation_move_pct, 4),
                    }
                    self.s1_rejections.append(item)
                    print(f"[S1] {item['check_time'][5:]} | Binance OPEN: "
                          f"{entry_s1['distance_pct']:.3f}% от S1 | "
                          f"пропуск до {item['cooldown_until'][5:]}")
                    continue

            exit_info = find_exit(
                candles, entry, "SHORT", cfg.TP_PCT, cfg.SL_PCT,
                cfg.TIMEOUT_MINUTES, include_entry_candle=include_entry_candle
            )
            if exit_info is None:
                self.filter_counts["missing_exit_data"] += 1
                continue

            close_dt = exit_info["close_dt"]
            hold = int((close_dt - actual_dt).total_seconds() / 60)
            net = self._pnl(entry, float(exit_info["price"])) - self._fee(exit_info["status"])
            excursion = self._excursion_stats(candles, actual_dt, close_dt, entry, include_entry_candle)
            self.trades.append({
                "signal_time": signal_time,
                "entry_time": actual_dt.tz_convert("Asia/Almaty").strftime("%Y-%m-%d %H:%M"),
                "exit_time": exit_info["close_local"].strftime("%Y-%m-%d %H:%M"),
                "type": "SHORT",
                "entry_price": round(entry, 2),
                "confirmation_price": float(entry_record["price"]),
                "entry_drift_pct": round((entry / float(entry_record["price"]) - 1) * 100, 4),
                "entry_price_source": source,
                "exit_price": exit_info["price"],
                "hold_minutes": hold,
                "net_pnl_pct": round(net, 2),
                "result": exit_info["status"],
                "exit_reason": exit_info["reason"],
                **excursion,
                "confirmation_delay_min": round(confirmation_delay, 1),
                "confirmation_move_pct": round(confirmation_move_pct, 3),
                "entry_dOI": entry_record["dOI"],
                "entry_dPrice": entry_record["dPrice"],
                "entry_volume": entry_record["volume"],
                "entry_taker_buy": entry_record["taker_buy"],
                "entry_zone": entry_record["in_zone"],
                "distance_to_s1_pct": round(s1["distance_pct"], 4) if s1 is not None else None,
                "s1_low": s1["zone_low"] if s1 is not None else None,
                "s1_high": s1["zone_high"] if s1 is not None else None,
            })
            last_closed_time = close_dt
            state_active = True

            label = {"WIN": "TP", "LOSS": "SL", "TIMEOUT": "TIMEOUT"}[exit_info["status"]]
            print(f"{actual_dt.tz_convert('Asia/Almaty').strftime('%d.%m %H:%M')}  "
                  f"SHORT  {entry:,.1f} -> {float(exit_info['price']):,.1f}  "
                  f"{label:<7} {net:+.2f}%  {hold} мин")

        print(f"S1: отклонено {self.filter_counts['support_near']} "
              f"(на Binance OPEN {self.filter_counts['support_entry_near']}), "
              f"пауза пропустила {self.filter_counts['support_cooldown']} наблюдений")
        if self.filter_counts["missing_entry_candle"] or self.filter_counts["missing_exit_data"]:
            print(f"Данные: нет свечи входа {self.filter_counts['missing_entry_candle']}, "
                  f"не завершены/не хватает свечей {self.filter_counts['missing_exit_data']}")
