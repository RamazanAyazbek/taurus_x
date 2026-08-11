import os
import json
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta


class TodaySessionScanner:
    def __init__(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1h",
        timezone_offset: int = 5,  # GMT+5
        baseline_file: str = "baseline_metrics.json"
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.timezone_offset = timezone_offset
        self.baseline_file = baseline_file
        self.base_url = "https://fapi.binance.com"
        self.baseline = self.load_baseline()

    def load_baseline(self) -> dict:
        """Загружает базовые медианы из baseline_metrics.json"""
        if not os.path.exists(self.baseline_file):
            raise FileNotFoundError(
                f"❌ Файл '{self.baseline_file}' не найден! "
                f"Сначала запустите 'baseline_calculator.py'."
            )

        with open(self.baseline_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def fetch_realtime_oi(self) -> float:
        """Получает текущий Открытый Интерес без задержек"""
        try:
            url = f"{self.base_url}/fapi/v1/openInterest"
            res = requests.get(url, params={"symbol": self.symbol}).json()
            return float(res['openInterest'])
        except Exception:
            return 0.0

    def fetch_market_snapshot(self) -> pd.DataFrame:
        """Загружает свечи и OI из Binance API"""
        offset_hours = timedelta(hours=self.timezone_offset)
        tz_info = timezone(offset_hours)

        # 1. Загрузка свечей
        klines_url = f"{self.base_url}/fapi/v1/klines"
        params_klines = {"symbol": self.symbol, "interval": self.timeframe, "limit": 48}
        res_klines = requests.get(klines_url, params=params_klines).json()

        df_klines = pd.DataFrame(res_klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
            'taker_buy_quote_volume', 'ignore'
        ])

        cols = ['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']
        df_klines[cols] = df_klines[cols].astype(float)

        df_klines['time'] = (
            pd.to_datetime(df_klines['open_time'], unit='ms', utc=True)
            .dt.tz_convert(tz_info)
            .dt.tz_localize(None)
        )

        # 2. История OI
        oi_url = f"{self.base_url}/futures/data/openInterestHist"
        params_oi = {"symbol": self.symbol, "period": self.timeframe, "limit": 48}
        res_oi = requests.get(oi_url, params=params_oi).json()

        df_oi = pd.DataFrame(res_oi)
        df_oi['sumOpenInterest'] = df_oi['sumOpenInterest'].astype(float)
        df_oi['time'] = (
            pd.to_datetime(df_oi['timestamp'], unit='ms', utc=True)
            .dt.tz_convert(tz_info)
            .dt.tz_localize(None)
        )

        # 3. Объединение
        df = pd.merge_asof(
            df_klines.sort_values('time'),
            df_oi[['time', 'sumOpenInterest']].sort_values('time'),
            on='time',
            direction='nearest'
        ).rename(columns={'sumOpenInterest': 'oi', 'taker_buy_volume': 'buy_volume'})

        df['price_change_pct'] = df['close'].pct_change() * 100
        df['oi_change_pct'] = df['oi'].pct_change() * 100

        return df

    def classify_candle(self, price_ch: float, oi_ch: float, vol_ratio: float) -> str:
        """Классификация типа свечи по динамике цены, OI и объему"""
        is_high_volume = vol_ratio >= 1.3

        if is_high_volume:
            if price_ch > 0 and oi_ch > 0:
                return "🟢 BULL_IMPULSE"
            elif price_ch < 0 and oi_ch > 0:
                return "🔴 BEAR_IMPULSE"
            elif price_ch > 0 and oi_ch < 0:
                return "⚡ SHORT_SQUEEZE"
            elif price_ch < 0 and oi_ch < 0:
                return "💥 LONG_LIQUID"

        if price_ch > 0.3:
            return "📈 BULLISH"
        elif price_ch < -0.3:
            return "📉 BEARISH"

        return "⚪ FLAT"

    def evaluate_today(self):
        """Анализирует всю динамику сегодняшнего дня от 00:00 UTC (05:00 GMT+5) до текущей минуты"""
        df = self.fetch_market_snapshot()
        df_closed = df.iloc[:-1].copy()
        live_candle = df.iloc[-1]

        offset_hours = timedelta(hours=self.timezone_offset)
        now_time = datetime.now(timezone.utc).astimezone(timezone(offset_hours)).replace(tzinfo=None)

        # Старт сегодняшних суток (05:00 GMT+5 соответствует 00:00 UTC)
        today_start = now_time.replace(hour=5, minute=0, second=0, microsecond=0)
        if now_time < today_start:
            today_start -= timedelta(days=1)

        # Фильтруем закрытые свечи за сегодня
        df_today = df_closed[df_closed['time'] >= today_start].copy()

        vol_med = self.baseline['volume']['median']
        oi_med = self.baseline['abs_doi']['median']

        print("\n" + "=" * 90)
        print(f"📊 TODAY'S SESSION HISTORY ({self.symbol}) | Start: [{today_start.strftime('%Y-%m-%d %H:%M')}]")
        # print(f"🎯 Baseline (30D Workdays) -> Vol Median: {vol_med} | |dOI| Median: {oi_med}%")
        print("=" * 90)

        bullish_impulses = 0
        bearish_impulses = 0
        short_squeezes = 0
        long_liquids = 0

        if not df_today.empty:
            for _, row in df_today.iterrows():
                t_str = row['time'].strftime('%H:00')
                p_ch = row['price_change_pct']
                oi_ch = row['oi_change_pct']
                vol = row['volume']

                vol_ratio = vol / vol_med if vol_med > 0 else 1.0
                tag = self.classify_candle(p_ch, oi_ch, vol_ratio)

                if "BULL_IMPULSE" in tag: bullish_impulses += 1
                elif "BEAR_IMPULSE" in tag: bearish_impulses += 1
                elif "SHORT_SQUEEZE" in tag: short_squeezes += 1
                elif "LONG_LIQUID" in tag: long_liquids += 1

                print(
                    f"[{t_str}] Close: {row['close']} | "
                    f"dPrice: {p_ch:+.2f}% | "
                    f"dOI: {oi_ch:+.2f}% | "
                    f"Vol: {vol:.0f} ({vol_ratio:.2f}x Med) | "
                    f"Tag: {tag}"
                )

            # Накопленные итоги дня
            p_start = df_today.iloc[0]['open']
            p_end = df_today.iloc[-1]['close']
            today_p_change = ((p_end - p_start) / p_start) * 100

            oi_start = df_today.iloc[0]['oi']
            oi_end = df_today.iloc[-1]['oi']
            today_oi_change = ((oi_end - oi_start) / oi_start) * 100 if oi_start > 0 else 0.0

            # Оценка характера дня
            if today_p_change > 0.5 and today_oi_change > 0:
                bias = "🟢 BULLISH_ACCUMULATION (Покупатели набирают позиции)"
            elif today_p_change < -0.5 and today_oi_change > 0:
                bias = "🔴 BEARISH_ACCUMULATION (Продавцы давят рынок)"
            elif today_p_change > 0.5 and today_oi_change < 0:
                bias = "⚡ SHORT_COVERING (Рост на закрытии шортов)"
            elif today_p_change < -0.5 and today_oi_change < 0:
                bias = "💥 LONG_UNWINDING (Падение на сбросе лонгов)"
            else:
                bias = "⚪ RANGE / CONSOLIDATION (Флэт / Нет четкого тренда)"

            print("-" * 90)
            print(f"📈 Today's Price Change : {today_p_change:+.2f}%")
            print(f"📊 Today's OI Change    : {today_oi_change:+.2f}%")
            print(f"⚡ Key Events          : Bull Impulses: {bullish_impulses} | Bear Impulses: {bearish_impulses} | Squeezes/Liquids: {short_squeezes + long_liquids}")
            print(f"💡 DAY EVALUATION       : {bias}")
        else:
            print("⏳ Ожидание закрытия первого часа текущего дня...")

        # print("=" * 90)

        # Текущая лайв-свеча
        minutes_passed = max(1, min(int((now_time - live_candle['time']).total_seconds() // 60), 60))
        vol_curr = live_candle['volume']
        proj_vol = (vol_curr / minutes_passed) * 60
        proj_vol_ratio = proj_vol / vol_med if vol_med > 0 else 1.0

        live_p_pct = ((live_candle['close'] - live_candle['open']) / live_candle['open']) * 100

        realtime_oi = self.fetch_realtime_oi()
        last_closed_oi = df_closed.iloc[-1]['oi']
        live_oi_pct = ((realtime_oi - last_closed_oi) / last_closed_oi) * 100 if last_closed_oi > 0 else 0.0

        live_tag = self.classify_candle(live_p_pct, live_oi_pct, proj_vol_ratio)

        # print(
        #     f"🔴 LIVE [{now_time.strftime('%H:%M')} | {minutes_passed}m/60m] "
        #     f"Price: {live_candle['close']} ({live_p_pct:+.2f}%) | "
        #     f"dOI: {live_oi_pct:+.2f}% | "
        #     f"ProjVol: {proj_vol_ratio:.2f}x Med | "
        #     f"Status: {live_tag}"
        # )
        # print("=" * 90 + "\n")


if __name__ == "__main__":
    scanner = TodaySessionScanner(
        symbol="BTCUSDT",
        timeframe="1h",
        timezone_offset=5,
        baseline_file="baseline_metrics.json"
    )
    scanner.evaluate_today()