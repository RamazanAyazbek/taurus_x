import requests
import pandas as pd
import time
import json
import os
import traceback
from datetime import datetime, timezone, timedelta

# Импортируем детектор уровней
from level_detector import LevelDetector


class BinanceFuturesLivePrinter:
    def __init__(self, symbol: str = "BTCUSDT", timeframe: str = "1h", timezone_offset: int = 5):
        self.symbol = symbol
        self.timeframe = timeframe
        self.timezone_offset = timezone_offset
        self.base_url = "https://fapi.binance.com"

        self.json_filename = "baseline_metrics.json"
        self.vol_median = self._load_vol_median_from_json()

        # Храним ID текущей свечи, чтобы фиксировать закрытие часа
        self.current_candle_open_ms = None

        self.detector = LevelDetector(
            symbol=self.symbol,
            baseline_file=self.json_filename,
            timezone_offset=self.timezone_offset
        )

    def get_live_data_silent_or_check(self):
        try:
            res_klines = requests.get(f"{self.base_url}/fapi/v1/klines",
                                      params={"symbol": self.symbol, "interval": self.timeframe, "limit": 1}).json()
            if isinstance(res_klines, list) and len(res_klines) > 0:
                return res_klines[-1][0]
        except Exception:
            pass
        return None

    def _load_vol_median_from_json(self) -> float:
        default_median = 1500.0
        if os.path.exists(self.json_filename):
            try:
                with open(self.json_filename, "r", encoding="utf-8") as f:
                    metrics = json.load(f)

                if "volume" in metrics and "median" in metrics["volume"]:
                    return float(metrics["volume"]["median"])

                for key in ["vol_median", "Volume", "vol"]:
                    if key in metrics:
                        if isinstance(metrics[key], dict):
                            for sub_key in ["Median", "median", "vol_median"]:
                                if sub_key in metrics[key]:
                                    return float(metrics[key][sub_key])
                        else:
                            return float(metrics[key])
            except Exception as e:
                print(f"❌ Ошибка при чтении или парсинге JSON: {e}")
        return default_median

    def check_zone_intersection(self, candle_high: float, candle_low: float, current_price: float) -> str:
        """
        Идентифицирует зоны как S1, S2... и R1, R2... и возвращает компактную строку.
        """
        try:
            tracked_data = self.detector.get_tracked_zones()
            zones = tracked_data.get("zones", [])
            if not zones:
                return ""

            # Разделяем зоны относительно текущей цены
            supports = [z for z in zones if z['ceil'] <= current_price or z['core_price'] <= current_price]
            resistances = [z for z in zones if z['floor'] >= current_price or z['core_price'] > current_price]

            # Сортируем: S1 — ближайшая снизу, R1 — ближайшая сверху
            supports = sorted(supports, key=lambda x: x['core_price'], reverse=True)
            resistances = sorted(resistances, key=lambda x: x['core_price'], reverse=False)

            # Назначаем имена S1, S2... R1, R2...
            for idx, z in enumerate(supports, start=1):
                z['tag'] = f"S{idx}"
            for idx, z in enumerate(resistances, start=1):
                z['tag'] = f"R{idx}"

            hit_zones = []
            for z in (supports + resistances):
                # Проверка пересечения свечи [low, high] с зоной [floor, ceil]
                if not (candle_high < z['floor'] or candle_low > z['ceil']):
                    # Форматируем компактно цены: 62547 -> 62.5k
                    f_k = f"{z['floor'] / 1000:.1f}k"
                    c_k = f"{z['ceil'] / 1000:.1f}k"
                    hit_zones.append(f"{z['tag']}[{f_k}-{c_k}]")

            if hit_zones:
                return f" | 🎯 IN: {', '.join(hit_zones)}"
            return ""
        except Exception:
            return ""

    def get_live_data(self, force_summary_for_closed=None):
        klines_url = f"{self.base_url}/fapi/v1/klines"
        params = {"symbol": self.symbol, "interval": self.timeframe, "limit": 3}

        try:
            res_klines = requests.get(klines_url, params=params).json()
            if not isinstance(res_klines, list) or len(res_klines) < 2:
                return None
        except Exception as e:
            print(f"❌ Ошибка сети при запросе свечей: {e}")
            return None

        # --- ВЫВОД ИТОГОВ ЗАКРЫТОГО ЧАСА ---
        if force_summary_for_closed:
            closed_candle = None
            for k in res_klines:
                if k[0] == force_summary_for_closed:
                    closed_candle = k
                    break

            if closed_candle:
                self._print_hourly_summary(closed_candle)
            return None

        # --- ОПЕРАТИВНЫЙ МОНИТОРИНГ ---
        active_candle = res_klines[-1]
        open_time_ms = active_candle[0]

        try:
            c_open = float(active_candle[1])
            c_high = float(active_candle[2])
            c_low = float(active_candle[3])
            c_close = float(active_candle[4])
            c_volume = float(active_candle[5])
            c_taker_volume = float(active_candle[9])
        except (IndexError, ValueError, TypeError):
            return None

        candle_open_time_utc = pd.to_datetime(open_time_ms, unit='ms', utc=True)
        now_time_utc = datetime.now(timezone.utc)

        minutes_passed = int((now_time_utc - candle_open_time_utc).total_seconds() // 60)
        minutes_passed = max(1, min(minutes_passed, 60))
        local_output_time = now_time_utc + timedelta(hours=self.timezone_offset)

        # Данные OI
        realtime_oi = 0.0
        try:
            res_oi = requests.get(f"{self.base_url}/fapi/v1/openInterest", params={"symbol": self.symbol}).json()
            if isinstance(res_oi, dict) and 'openInterest' in res_oi:
                realtime_oi = float(res_oi['openInterest'])
        except Exception:
            pass

        last_closed_oi = 0.0
        try:
            res_hist = requests.get(f"{self.base_url}/futures/data/openInterestHist",
                                    params={"symbol": self.symbol, "period": self.timeframe, "limit": 2}).json()
            if isinstance(res_hist, list) and len(res_hist) > 0:
                last_closed_oi = float(res_hist[-1]['sumOpenInterest'])
        except Exception:
            pass

        try:
            live_price_pct = ((c_close - c_open) / c_open) * 100 if c_open > 0 else 0.0
            live_oi_pct = ((realtime_oi - last_closed_oi) / last_closed_oi) * 100 if (
                        realtime_oi > 0 and last_closed_oi > 0) else 0.0
            oi_speed = live_oi_pct / minutes_passed

            projected_volume = (c_volume / minutes_passed) * 60
            base_med = self.vol_median if self.vol_median > 0 else 1500.0
            projected_vol_ratio = projected_volume / base_med

            taker_buy_pct = (c_taker_volume / c_volume * 100) if c_volume > 0 else 0.0

            # Сжатая проверка попадания в зоны S1/R1
            zone_str = self.check_zone_intersection(candle_high=c_high, candle_low=c_low, current_price=c_close)
        except Exception as e:
            print(f"❌ Ошибка математики: {e}")
            return open_time_ms

        # Однострочный компактный вывод
        try:
            console_output = (
                f"[{local_output_time.strftime('%H:%M')} | {minutes_passed}m/60m] "
                f"BTC: {c_close:.1f} ({live_price_pct:+.2f}%) [H:{c_high:.1f}|L:{c_low:.1f}] | "
                f"dOI: {live_oi_pct:+.2f}% (Spd: {oi_speed:+.4f}%/m) | "
                f"Vol: {c_volume:.0f} (Proj: {projected_vol_ratio:.2f}x Med) | "
                f"TakerBuy: {taker_buy_pct:.1f}%"
                f"{zone_str}"
            )
            print(console_output, flush=True)
        except Exception as e:
            print(f"❌ Ошибка вывода: {e}")

        return open_time_ms

    def _print_hourly_summary(self, candle):
        """Отчет при закрытии часовой свечи"""
        try:
            open_time_ms = candle[0]
            c_open = float(candle[1])
            c_high = float(candle[2])
            c_low = float(candle[3])
            c_close = float(candle[4])
            c_volume = float(candle[5])

            price_change_pct = ((c_close - c_open) / c_open) * 100 if c_open > 0 else 0.0

            if c_close > c_open:
                status = "🟢 BULLISH"
            elif c_close < c_open:
                status = "🔴 BEARISH"
            else:
                status = "⚪️ DOJI"

            open_time_local = pd.to_datetime(open_time_ms, unit='ms', utc=True) + timedelta(hours=self.timezone_offset)

            print(
                f"\n⏰ ИТОГ ЧАСА ({open_time_local.strftime('%H:%M')}): {status} | Изм: {price_change_pct:+.2f}% ({c_open:.1f} -> {c_close:.1f}) | Range: [{c_low:.1f} - {c_high:.1f}] | Vol: {c_volume:.0f}\n",
                flush=True)

        except Exception as e:
            print(f"❌ Ошибка вывода итога часа: {e}")