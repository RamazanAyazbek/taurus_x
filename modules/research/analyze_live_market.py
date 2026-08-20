import json
import os
import time
import traceback
from datetime import datetime, timedelta, timezone
import pandas as pd
import requests

from level_detector import LevelDetector


class BinanceFuturesLivePrinter:

  def __init__(
      self,
      symbol: str = "BTCUSDT",
      timeframe: str = "1h",
      timezone_offset: int = 5,
  ):
    self.symbol = symbol
    self.timeframe = timeframe
    self.timezone_offset = timezone_offset
    self.base_url = "https://fapi.binance.com"

    self.json_filename = "baseline_metrics.json"

    # Загружаем медианы СТРОГО из JSON
    self.vol_median = self._load_vol_median_from_json()
    self.oi_median = self._get_oi_median_from_json()

    # Динамически вычисляем эталонную скорость (в минуту) на основе часовой медианы dOI
    self.oi_speed_median = self.oi_median / 60.0 if self.oi_median > 0 else 0.0

    self.last_reported_closed_candle = None

    self.detector = LevelDetector(
        symbol=self.symbol,
        baseline_file=self.json_filename,
        timezone_offset=self.timezone_offset,
    )

  def _load_vol_median_from_json(self) -> float:
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
        print(f"❌ Ошибка чтения медианы Volume из JSON: {e}")

    print(f"⚠️ Не удалось прочитать Volume из {self.json_filename}! Задано 0.0")
    return 0.0

  def _get_oi_median_from_json(self) -> float:
    if os.path.exists(self.json_filename):
      try:
        with open(self.json_filename, "r", encoding="utf-8") as f:
          metrics = json.load(f)

        if "abs_doi" in metrics and "median" in metrics["abs_doi"]:
          return float(metrics["abs_doi"]["median"])

        for key in ["doi", "oi", "open_interest"]:
          if key in metrics and isinstance(metrics[key], dict):
            if "median" in metrics[key]:
              return float(metrics[key]["median"])

      except Exception as e:
        print(f"❌ Ошибка чтения медианы dOI из JSON: {e}")

    print(f"⚠️ Не удалось прочитать dOI из {self.json_filename}! Задано 0.0")
    return 0.0

  def check_zone_intersection(
      self, candle_high: float, candle_low: float, current_price: float
  ) -> str:
    try:
      tracked_data = self.detector.get_tracked_zones()
      zones = tracked_data.get("zones", [])
      if not zones:
        return ""

      supports = [
          z
          for z in zones
          if z["ceil"] <= current_price or z["core_price"] <= current_price
      ]
      resistances = [
          z
          for z in zones
          if z["floor"] >= current_price or z["core_price"] > current_price
      ]

      supports = sorted(supports, key=lambda x: x["core_price"], reverse=True)
      resistances = sorted(
          resistances, key=lambda x: x["core_price"], reverse=False
      )

      for idx, z in enumerate(supports, start=1):
        z["tag"] = f"S{idx}"
      for idx, z in enumerate(resistances, start=1):
        z["tag"] = f"R{idx}"

      hit_zones = []
      for z in supports + resistances:
        if not (candle_high < z["floor"] or candle_low > z["ceil"]):
          f_k = f"{z['floor'] / 1000:.1f}k"
          c_k = f"{z['ceil'] / 1000:.1f}k"
          hit_zones.append(f"{z['tag']}[{f_k}-{c_k}]")

      if hit_zones:
        return f" | 🎯 IN: {', '.join(hit_zones)}"
      return ""
    except Exception:
      return ""

  def _print_hourly_summary(self, candle):
    try:
      open_time_ms = candle[0]
      c_open = float(candle[1])
      c_high = float(candle[2])
      c_low = float(candle[3])
      c_close = float(candle[4])
      c_volume = float(candle[5])
      c_taker_volume = float(candle[9])

      price_change_pct = (
          ((c_close - c_open) / c_open) * 100 if c_open > 0 else 0.0
      )
      flat_threshold = 0.05

      if abs(price_change_pct) < flat_threshold:
        status = "⚪️ FLAT/DOJI"
      elif price_change_pct >= flat_threshold:
        status = "🟢 BULLISH"
      else:
        status = "🔴 BEARISH"

      vol_ratio = (
          (c_volume / self.vol_median) if self.vol_median > 0 else 0.0
      )
      taker_buy_pct = (
          (c_taker_volume / c_volume * 100) if c_volume > 0 else 0.0
      )

      last_closed_oi, prev_closed_oi = 0.0, 0.0
      try:
        res_hist = requests.get(
            f"{self.base_url}/futures/data/openInterestHist",
            params={
                "symbol": self.symbol,
                "period": self.timeframe,
                "limit": 3,
            },
        ).json()
        if isinstance(res_hist, list) and len(res_hist) >= 2:
          last_closed_oi = float(res_hist[-1]["sumOpenInterest"])
          prev_closed_oi = float(res_hist[-2]["sumOpenInterest"])
      except Exception:
        pass

      hourly_doi_pct = 0.0
      if last_closed_oi > 0 and prev_closed_oi > 0:
        hourly_doi_pct = (
            (last_closed_oi - prev_closed_oi) / prev_closed_oi
        ) * 100

      doi_ratio = (
          abs(hourly_doi_pct) / self.oi_median if self.oi_median > 0 else 0.0
      )

      zone_str = self.check_zone_intersection(
          candle_high=c_high, candle_low=c_low, current_price=c_close
      )

      open_time_local = pd.to_datetime(
          open_time_ms, unit="ms", utc=True
      ) + timedelta(hours=self.timezone_offset)

      print("\n" + "=" * 90, flush=True)
      print(
          f"⏰ ИТОГ ЧАСА [{open_time_local.strftime('%H:00-59')}]: {status} |"
          f" Изм: {price_change_pct:+.2f}% ({c_open:.1f} -> {c_close:.1f})",
          flush=True,
      )
      print(
          f"   📊 [H:{c_high:.1f} | L:{c_low:.1f}] | dOI: {hourly_doi_pct:+.2f}%"
          f" ({doi_ratio:.2f}x Med) | Vol: {c_volume:.0f} ({vol_ratio:.2f}x"
          f" Med) | TakerBuy: {taker_buy_pct:.1f}%{zone_str}",
          flush=True,
      )
      print("=" * 90 + "\n", flush=True)

    except Exception as e:
      print(f"❌ Ошибка вывода итога часа: {e}")

  def process_step(self):
      """Единый шаг расчета и вывода лога каждые 10 минут."""
      klines_url = f"{self.base_url}/fapi/v1/klines"
      params = {"symbol": self.symbol, "interval": self.timeframe, "limit": 3}

      try:
        res_klines = requests.get(klines_url, params=params).json()
        if not isinstance(res_klines, list) or len(res_klines) < 2:
          return
      except Exception as e:
        print(f"❌ Ошибка сети: {e}")
        return

      # 1. Проверяем и печатаем закрывшуюся свечу (ИТОГ ЧАСА)
      closed_candle = res_klines[-2]
      closed_open_ms = closed_candle[0]

      if self.last_reported_closed_candle != closed_open_ms:
        self._print_hourly_summary(closed_candle)
        self.last_reported_closed_candle = closed_open_ms

      # 2. Обрабатываем текущую свечу
      active_candle = res_klines[-1]
      open_time_ms = active_candle[0]

      c_open = float(active_candle[1])
      c_high = float(active_candle[2])
      c_low = float(active_candle[3])
      c_close = float(active_candle[4])
      c_volume = float(active_candle[5])
      c_taker_volume = float(active_candle[9])

      # Переменные объявляются СТРОГО перед использованием
      candle_open_time_utc = pd.to_datetime(open_time_ms, unit="ms", utc=True)
      now_time_utc = datetime.now(timezone.utc)

      minutes_passed = int(
          (now_time_utc - candle_open_time_utc).total_seconds() // 60
      )
      minutes_passed = max(1, min(minutes_passed, 60))
      local_output_time = now_time_utc + timedelta(hours=self.timezone_offset)

      # Не печатаем промежуточные логи в первые 3 минуты нового часа (чтобы не дублировать ИТОГ ЧАСА)
      if minutes_passed < 3:
        return

      # Запрос данных по Open Interest
      realtime_oi = 0.0
      try:
        res_oi = requests.get(
            f"{self.base_url}/fapi/v1/openInterest",
            params={"symbol": self.symbol},
        ).json()
        if isinstance(res_oi, dict) and "openInterest" in res_oi:
          realtime_oi = float(res_oi["openInterest"])
      except Exception:
        pass

      last_closed_oi = 0.0
      try:
        res_hist = requests.get(
            f"{self.base_url}/futures/data/openInterestHist",
            params={
                "symbol": self.symbol,
                "period": self.timeframe,
                "limit": 2,
            },
        ).json()
        if isinstance(res_hist, list) and len(res_hist) > 0:
          last_closed_oi = float(res_hist[-1]["sumOpenInterest"])
      except Exception:
        pass

      live_price_pct = (
          ((c_close - c_open) / c_open) * 100 if c_open > 0 else 0.0
      )
      live_oi_pct = (
          ((realtime_oi - last_closed_oi) / last_closed_oi) * 100
          if (realtime_oi > 0 and last_closed_oi > 0)
          else 0.0
      )

      # --- РАСЧЕТ ОТНОСИТЕЛЬНЫХ МЕТРИК OI И SPEED ---
      oi_ratio = (
          abs(live_oi_pct) / self.oi_median if self.oi_median > 0 else 0.0
      )

      oi_speed = live_oi_pct / minutes_passed
      oi_speed_ratio = (
          abs(oi_speed) / self.oi_speed_median
          if self.oi_speed_median > 0
          else 0.0
      )

      # --- РАСЧЕТ ПРОЕКЦИИ ОБЪЕМА ---
      projected_volume = (c_volume / minutes_passed) * 60
      projected_vol_ratio = (
          (projected_volume / self.vol_median) if self.vol_median > 0 else 0.0
      )

      taker_buy_pct = (
          (c_taker_volume / c_volume * 100) if c_volume > 0 else 0.0
      )

      zone_str = self.check_zone_intersection(
          candle_high=c_high, candle_low=c_low, current_price=c_close
      )

      # Формируем наглядную строку вывода
      console_output = (
          f"[{local_output_time.strftime('%Y-%m-%d %H:%M')} |"
          f" {minutes_passed}m/60m] BTC: {c_close:.1f} ({live_price_pct:+.2f}%)"
          f" [H:{c_high:.1f}|L:{c_low:.1f}] | dOI: {live_oi_pct:+.2f}%"
          f" ({oi_ratio:.2f}x Med) | Spd: {oi_speed_ratio:.2f}x Med | Vol:"
          f" {c_volume:.0f} (Proj: {projected_vol_ratio:.2f}x Med) | TakerBuy:"
          f" {taker_buy_pct:.1f}%{zone_str}"
      )
      print(console_output, flush=True)


  def start_loop(self):
    print(f"🚀 Запуск мониторинга {self.symbol}... Ожидание сетки времени...")
    while True:
      try:
        self.process_step()

        now = datetime.now()
        next_minute = (now.minute // 10 + 1) * 10
        if next_minute == 60:
          next_time = now.replace(
              minute=0, second=2, microsecond=0
          ) + timedelta(hours=1)
        else:
          next_time = now.replace(minute=next_minute, second=2, microsecond=0)

        sleep_seconds = (next_time - now).total_seconds()
        if sleep_seconds > 0:
          time.sleep(sleep_seconds)

      except KeyboardInterrupt:
        print("\n⏹ Мониторинг остановлен.")
        break
      except Exception as e:
        print(f"❌ Непредвиденная ошибка в цикле: {e}")
        time.sleep(10)


if __name__ == "__main__":
  printer = BinanceFuturesLivePrinter(
      symbol="BTCUSDT", timeframe="1h", timezone_offset=5
  )
  printer.start_loop()