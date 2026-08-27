import re
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict


# ============================================================
# CONFIG
# ============================================================

@dataclass
class Config:

    # Position
    leverage: int = 10
    sl_points: float = 300.0

    # Costs
    commission_pct: float = 0.04
    slippage_pct: float = 0.02

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    # Минимальное количество подтверждений
    min_confirmations: int = 2

    # Для сильного сигнала
    strong_confirmations: int = 4

    # --------------------------------------------------------
    # MEDIAN MULTIPLIERS
    # --------------------------------------------------------

    # Volume:
    # 1.0 = медиана
    # 2.0 = в 2 раза выше медианы
    volume_normal: float = 1.0
    volume_strong: float = 2.0
    volume_extreme: float = 3.0

    # Price:
    # насколько движение должно быть относительно медианы
    price_normal: float = 1.0
    price_strong: float = 1.5

    # OI
    oi_normal: float = 1.0
    oi_strong: float = 1.5

    # --------------------------------------------------------
    # TAKER BUY
    # --------------------------------------------------------

    taker_neutral_low: float = 48.0
    taker_neutral_high: float = 52.0

    taker_long: float = 53.0
    taker_strong_long: float = 55.0

    taker_short: float = 47.0
    taker_strong_short: float = 45.0

    # --------------------------------------------------------
    # EXIT
    # --------------------------------------------------------

    # Минимум часов до проверки истощения.
    # Не закрываем позицию сразу после первого слабого часа.
    min_hold_hours: int = 2

    # Сколько признаков должно указывать на истощение.
    exhaustion_confirmations: int = 2

    # Price change около нуля
    stagnation_multiplier: float = 0.5

    # Максимальный срок только как страховка.
    # Это НЕ TP.
    max_hold_hours: int = 48


# ============================================================
# DATA
# ============================================================

@dataclass
class HourlyData:

    timestamp: datetime

    open_price: float
    close_price: float

    high: float
    low: float

    price_change: float

    oi_change: float

    volume: float

    volume_ratio: float

    taker_buy: float

    sentiment: str


@dataclass
class Signal:

    direction: str

    confidence: str

    score_long: int

    score_short: int

    confirmations: List[str]

    price_vs_median: float

    oi_vs_median: float

    volume_vs_median: float

    trend_state: str


@dataclass
class Trade:

    trade_number: int

    entry_time: str
    entry_price: float

    direction: str

    confidence: str

    score_long: int
    score_short: int

    entry_reasons: List[str]

    sl_price: float

    exit_time: Optional[str] = None
    exit_price: Optional[float] = None

    result: Optional[str] = None

    pnl_points: float = 0.0
    pnl_percent: float = 0.0

    holding_hours: float = 0.0

    max_favorable_points: float = 0.0
    max_adverse_points: float = 0.0


# ============================================================
# TAURUS BACKTEST
# ============================================================

class TaurusBacktest:

    def __init__(
        self,
        log_file: str,
        config: Config
    ):

        self.log_file = log_file
        self.config = config

        self.data: List[HourlyData] = []

        self.volume_median = 0.0
        self.oi_median = 0.0
        self.price_median = 0.0

        self.trades: List[Trade] = []

        self.total_decisions = 0
        self.no_trade = 0

    # ========================================================
    # PARSE LOG
    # ========================================================

    def parse_log(self):

        print("🔍 Парсинг taurus_x_container.log...")

        with open(
            self.log_file,
            "r",
            encoding="utf-8"
        ) as f:

            content = f.read()

        # ----------------------------------------------------
        # MEDIANS
        # ----------------------------------------------------

        median_pattern = (
            r"Volume Median:\s*([+-]?[\d.]+)"
            r"\s*\|\s*dOI Median:\s*([+-]?[\d.]+)%"
            r"\s*\|\s*dPrice Median:\s*([+-]?[\d.]+)%"
        )

        median_match = re.search(
            median_pattern,
            content
        )

        if median_match:

            self.volume_median = float(
                median_match.group(1)
            )

            self.oi_median = abs(
                float(median_match.group(2))
            )

            self.price_median = abs(
                float(median_match.group(3))
            )

        else:

            print(
                "⚠️ Медианы не найдены!"
            )

        print()
        print("📊 MEDIANS")
        print(
            f"   Volume Median: "
            f"{self.volume_median:.4f}"
        )
        print(
            f"   dOI Median: "
            f"{self.oi_median:.4f}%"
        )
        print(
            f"   dPrice Median: "
            f"{self.price_median:.4f}%"
        )

        # ----------------------------------------------------
        # HOURLY DATA
        # ----------------------------------------------------

        hour_pattern = (
            r"⏰ ИТОГ ЧАСА "
            r"\((\d{2}:\d{2})\): "
            r"([^|]+)"
            r"\|\s*Изм:\s*"
            r"([+-]?[\d.]+)%\s*"
            r"\(([\d.]+)\s*->\s*([\d.]+)\)"
            r"\s*\|\s*Range:\s*"
            r"\[([\d.]+)\s*-\s*([\d.]+)\]"
            r"\s*\|\s*Vol:\s*([\d.]+)"
        )

        date_pattern = r"(\d{4}-\d{2}-\d{2})"

        current_date = None

        matches = list(
            re.finditer(
                hour_pattern,
                content
            )
        )

        for match in matches:

            pos = match.start()

            dates = re.findall(
                date_pattern,
                content[:pos]
            )

            if dates:

                current_date = dates[-1]

            if not current_date:

                continue

            hour = match.group(1)

            sentiment = (
                match.group(2)
                .strip()
            )

            price_change = float(
                match.group(3)
            )

            open_price = float(
                match.group(4)
            )

            close_price = float(
                match.group(5)
            )

            low = float(
                match.group(6)
            )

            high = float(
                match.group(7)
            )

            volume = float(
                match.group(8)
            )

            timestamp = datetime.strptime(
                f"{current_date} {hour}",
                "%Y-%m-%d %H:%M"
            )

            # ------------------------------------------------
            # OI
            #
            # ВАЖНО:
            # ищем OI непосредственно рядом
            # с соответствующим часом.
            # ------------------------------------------------

            oi_change = self.extract_oi(
                content,
                pos,
                hour
            )

            # ------------------------------------------------
            # TAKER BUY
            # ------------------------------------------------

            taker_buy = self.extract_taker(
                content,
                pos,
                hour
            )

            # ------------------------------------------------
            # VOLUME RATIO
            # ------------------------------------------------

            volume_ratio = (
                volume / self.volume_median
                if self.volume_median > 0
                else 0.0
            )

            # ------------------------------------------------
            # SENTIMENT
            # ------------------------------------------------

            if "BULLISH" in sentiment:

                sentiment_type = "BULLISH"

            elif "BEARISH" in sentiment:

                sentiment_type = "BEARISH"

            else:

                sentiment_type = "FLAT"

            self.data.append(
                HourlyData(

                    timestamp=timestamp,

                    open_price=open_price,

                    close_price=close_price,

                    high=high,

                    low=low,

                    price_change=price_change,

                    oi_change=oi_change,

                    volume=volume,

                    volume_ratio=volume_ratio,

                    taker_buy=taker_buy,

                    sentiment=sentiment_type
                )
            )

        self.data.sort(
            key=lambda x: x.timestamp
        )

        print()
        print(
            f"✅ Найдено "
            f"{len(self.data)} "
            f"часовых данных"
        )

        # ----------------------------------------------------
        # DATA DIAGNOSTICS
        # ----------------------------------------------------

        self.print_data_diagnostics()

    # ========================================================
    # OI PARSER
    # ========================================================

    def extract_oi(
        self,
        content: str,
        position: int,
        hour: str
    ) -> float:

        start = max(
            0,
            position - 2000
        )

        end = min(
            len(content),
            position + 2000
        )

        block = content[start:end]

        pattern = (
            rf"\[{re.escape(hour)}\]"
            r"[^\n]*?"
            r"dOI:\s*"
            r"([+-]?[\d.]+)%"
        )

        matches = re.findall(
            pattern,
            block
        )

        if not matches:

            return 0.0

        try:

            return float(
                matches[-1]
            )

        except ValueError:

            return 0.0

    # ========================================================
    # TAKER PARSER
    # ========================================================

    def extract_taker(
        self,
        content: str,
        position: int,
        hour: str
    ) -> float:

        start = max(
            0,
            position - 3000
        )

        end = min(
            len(content),
            position + 3000
        )

        block = content[start:end]

        pattern = (
            rf"\[{re.escape(hour)}"
            r"[^\]]*\]"
            r"[^\n]*?"
            r"TakerBuy:\s*"
            r"([\d.]+)%"
        )

        matches = re.findall(
            pattern,
            block
        )

        if not matches:

            return 50.0

        try:

            return float(
                matches[-1]
            )

        except ValueError:

            return 50.0

    # ========================================================
    # DIAGNOSTICS
    # ========================================================

    def print_data_diagnostics(self):

        if not self.data:

            return

        oi_zero = sum(
            1
            for x in self.data
            if x.oi_change == 0
        )

        taker_default = sum(
            1
            for x in self.data
            if x.taker_buy == 50
        )

        print()
        print("🔎 ПРОВЕРКА ДАННЫХ")
        print(
            f"   OI = 0: "
            f"{oi_zero}/{len(self.data)}"
        )

        print(
            f"   TakerBuy = 50: "
            f"{taker_default}/{len(self.data)}"
        )

        print()
        print(
            "Последние 5 часов:"
        )

        for x in self.data[-5:]:

            print(
                f"   "
                f"{x.timestamp} | "
                f"{x.sentiment:<8} | "
                f"Price: {x.price_change:+.3f}% | "
                f"OI: {x.oi_change:+.3f}% | "
                f"Vol: {x.volume_ratio:.2f}x | "
                f"Taker: {x.taker_buy:.1f}%"
            )

    # ========================================================
    # MEDIAN HELPERS
    # ========================================================

    def price_strength(
        self,
        data: HourlyData
    ) -> float:

        if self.price_median <= 0:

            return 0.0

        return (
            abs(data.price_change)
            /
            self.price_median
        )

    def oi_strength(
        self,
        data: HourlyData
    ) -> float:

        if self.oi_median <= 0:

            return 0.0

        return (
            abs(data.oi_change)
            /
            self.oi_median
        )

    # ========================================================
    # SIGNAL ENGINE
    #
    # Здесь находится ВСЯ логика принятия решения.
    #
    # В будущем добавляем/удаляем правило именно здесь.
    # Backtest при этом не меняется.
    # ========================================================

    def get_signal(
        self,
        index: int
    ) -> Signal:

        current = self.data[index]

        previous = (
            self.data[index - 1]
            if index > 0
            else None
        )

        long_score = 0
        short_score = 0

        reasons = []

        # ====================================================
        # MEDIAN RATIOS
        # ====================================================

        volume_vs_median = (
            current.volume_ratio
        )

        price_vs_median = (
            self.price_strength(current)
        )

        oi_vs_median = (
            self.oi_strength(current)
        )

        # ====================================================
        # RULE 1
        # PRICE DIRECTION
        #
        # Сравниваем изменение цены
        # с dPrice Median.
        # ====================================================

        price_above_median = (
            price_vs_median
            >= self.config.price_normal
        )

        if price_above_median:

            if current.price_change > 0:

                long_score += 1

                reasons.append(
                    "PRICE_ABOVE_MEDIAN_LONG"
                )

            elif current.price_change < 0:

                short_score += 1

                reasons.append(
                    "PRICE_ABOVE_MEDIAN_SHORT"
                )

        # ====================================================
        # RULE 2
        # SENTIMENT
        # ====================================================

        if current.sentiment == "BULLISH":

            long_score += 1

            reasons.append(
                "BULLISH_HOUR"
            )

        elif current.sentiment == "BEARISH":

            short_score += 1

            reasons.append(
                "BEARISH_HOUR"
            )

        # ====================================================
        # RULE 3
        # VOLUME
        #
        # Не требуем > 3x.
        #
        # Уже превышение медианы = подтверждение.
        # 2x и 3x дают дополнительную силу.
        # ====================================================

        if (
            volume_vs_median
            >= self.config.volume_normal
        ):

            if current.price_change > 0:

                long_score += 1

                reasons.append(
                    "VOLUME_ABOVE_MEDIAN_LONG"
                )

            elif current.price_change < 0:

                short_score += 1

                reasons.append(
                    "VOLUME_ABOVE_MEDIAN_SHORT"
                )

        # Сильный объём
        if (
            volume_vs_median
            >= self.config.volume_strong
        ):

            if current.price_change > 0:

                long_score += 1

                reasons.append(
                    "STRONG_VOLUME_LONG"
                )

            elif current.price_change < 0:

                short_score += 1

                reasons.append(
                    "STRONG_VOLUME_SHORT"
                )

        # ====================================================
        # RULE 4
        # OI
        #
        # Смотрим направление изменения OI,
        # но силу определяем относительно медианы.
        # ====================================================

        if (
            oi_vs_median
            >= self.config.oi_normal
        ):

            if current.oi_change > 0:

                # Рост OI + рост цены
                # = подтверждение LONG

                if current.price_change > 0:

                    long_score += 1

                    reasons.append(
                        "OI_GROWTH_SUPPORTS_LONG"
                    )

                # Рост OI + падение цены
                # = подтверждение SHORT

                elif current.price_change < 0:

                    short_score += 1

                    reasons.append(
                        "OI_GROWTH_SUPPORTS_SHORT"
                    )

            elif current.oi_change < 0:

                # Падение OI само по себе
                # НЕ является автоматическим SHORT.
                #
                # Это важно.
                #
                # Старый код именно здесь
                # создавал много противоречий.

                reasons.append(
                    "OI_FALLING"
                )

        # ====================================================
        # RULE 5
        # TAKER BUY
        # ====================================================

        if (
            current.taker_buy
            >= self.config.taker_long
        ):

            long_score += 1

            reasons.append(
                "TAKER_BUY_LONG"
            )

        elif (
            current.taker_buy
            <= self.config.taker_short
        ):

            short_score += 1

            reasons.append(
                "TAKER_BUY_SHORT"
            )

        # ====================================================
        # RULE 6
        # STRONG TAKER
        # ====================================================

        if (
            current.taker_buy
            >= self.config.taker_strong_long
        ):

            long_score += 1

            reasons.append(
                "STRONG_TAKER_LONG"
            )

        elif (
            current.taker_buy
            <= self.config.taker_strong_short
        ):

            short_score += 1

            reasons.append(
                "STRONG_TAKER_SHORT"
            )

        # ====================================================
        # RULE 7
        # PREVIOUS MOMENTUM
        #
        # Смотрим не только текущий час,
        # но и предыдущий.
        #
        # Это позволяет увидеть,
        # что движение уже началось.
        # ====================================================

        if previous:

            if (
                previous.price_change
                > self.price_median
            ):

                if current.price_change > 0:

                    long_score += 1

                    reasons.append(
                        "CONTINUED_BULLISH_MOMENTUM"
                    )

            elif (
                previous.price_change
                < -self.price_median
            ):

                if current.price_change < 0:

                    short_score += 1

                    reasons.append(
                        "CONTINUED_BEARISH_MOMENTUM"
                    )

        # ====================================================
        # FINAL DIRECTION
        # ====================================================

        difference = abs(
            long_score -
            short_score
        )

        if (
            long_score
            >= self.config.min_confirmations
            and
            long_score > short_score
            and
            difference >= 1
        ):

            direction = "LONG"

        elif (
            short_score
            >= self.config.min_confirmations
            and
            short_score > long_score
            and
            difference >= 1
        ):

            direction = "SHORT"

        else:

            direction = "FLAT"

        # ====================================================
        # CONFIDENCE
        # ====================================================

        best_score = max(
            long_score,
            short_score
        )

        if best_score >= self.config.strong_confirmations:

            confidence = "HIGH"

        elif best_score >= 3:

            confidence = "MEDIUM"

        elif best_score >= 2:

            confidence = "LOW"

        else:

            confidence = "NONE"

        # ====================================================
        # TREND STATE
        # ====================================================

        if direction == "LONG":

            if best_score >= 4:

                trend_state = "STRONG_BULLISH"

            else:

                trend_state = "BULLISH"

        elif direction == "SHORT":

            if best_score >= 4:

                trend_state = "STRONG_BEARISH"

            else:

                trend_state = "BEARISH"

        else:

            trend_state = "UNDEFINED"

        return Signal(

            direction=direction,

            confidence=confidence,

            score_long=long_score,

            score_short=short_score,

            confirmations=reasons,

            price_vs_median=price_vs_median,

            oi_vs_median=oi_vs_median,

            volume_vs_median=volume_vs_median,

            trend_state=trend_state
        )

    # ========================================================
    # EXHAUSTION
    # ========================================================

    def check_exhaustion(
        self,
        trade: Trade,
        index: int
    ):

        current = self.data[index]

        previous = (
            self.data[index - 1]
            if index > 0
            else None
        )

        confirmations = 0
        reasons = []

        # ----------------------------------------------------
        # PRICE
        # ----------------------------------------------------

        if previous:

            if (
                abs(current.price_change)
                <=
                self.price_median
                *
                self.config.stagnation_multiplier
            ):

                confirmations += 1

                reasons.append(
                    "PRICE_STAGNATION"
                )

        # ----------------------------------------------------
        # OI
        # ----------------------------------------------------

        if (
            current.oi_change < 0
            and
            self.oi_median > 0
            and
            abs(current.oi_change)
            >= self.oi_median
        ):

            confirmations += 1

            reasons.append(
                "OI_LOSS"
            )

        # ----------------------------------------------------
        # TAKER
        # ----------------------------------------------------

        if trade.direction == "LONG":

            if (
                current.taker_buy
                < self.config.taker_neutral_high
            ):

                confirmations += 1

                reasons.append(
                    "LONG_TAKER_WEAK"
                )

        else:

            if (
                current.taker_buy
                > self.config.taker_neutral_low
            ):

                confirmations += 1

                reasons.append(
                    "SHORT_TAKER_WEAK"
                )

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        if (
            current.volume_ratio
            < self.config.volume_normal
        ):

            confirmations += 1

            reasons.append(
                "VOLUME_BELOW_MEDIAN"
            )

        # ----------------------------------------------------
        # OPPOSITE PRICE
        # ----------------------------------------------------

        if trade.direction == "LONG":

            if current.price_change < 0:

                confirmations += 1

                reasons.append(
                    "PRICE_TURNED_DOWN"
                )

        else:

            if current.price_change > 0:

                confirmations += 1

                reasons.append(
                    "PRICE_TURNED_UP"
                )

        exhausted = (
            confirmations
            >= self.config.exhaustion_confirmations
        )

        return exhausted, reasons

    # ========================================================
    # SL
    # ========================================================

    def check_sl(
        self,
        trade: Trade,
        candle: HourlyData
    ):

        if trade.direction == "LONG":

            if candle.low <= trade.sl_price:

                return True

        else:

            if candle.high >= trade.sl_price:

                return True

        return False

    # ========================================================
    # CLOSE
    # ========================================================

    def close_trade(
        self,
        trade: Trade,
        candle: HourlyData,
        result: str,
        exit_price: float
    ):

        if trade.direction == "LONG":

            pnl_points = (
                exit_price -
                trade.entry_price
            )

        else:

            pnl_points = (
                trade.entry_price -
                exit_price
            )

        # ----------------------------------------------------
        # COSTS
        # ----------------------------------------------------

        commission = (
            trade.entry_price
            *
            self.config.commission_pct
            / 100
            *
            2
        )

        slippage = (
            trade.entry_price
            *
            self.config.slippage_pct
            / 100
        )

        net_points = (
            pnl_points
            -
            commission
            -
            slippage
        )

        pnl_percent = (
            net_points
            /
            trade.entry_price
            *
            100
            *
            self.config.leverage
        )

        entry_time = datetime.fromisoformat(
            trade.entry_time
        )

        holding_hours = (
            candle.timestamp -
            entry_time
        ).total_seconds() / 3600

        trade.exit_time = (
            candle.timestamp.isoformat()
        )

        trade.exit_price = exit_price

        trade.result = result

        trade.pnl_points = pnl_points

        trade.pnl_percent = pnl_percent

        trade.holding_hours = holding_hours

        self.trades.append(
            trade
        )

        icon = (
            "✅"
            if pnl_percent > 0
            else "❌"
        )

        print()
        print(
            f"{icon} ЗАКРЫТИЕ "
            f"#{trade.trade_number}"
        )

        print(
            f"   {result}"
        )

        print(
            f"   Exit: "
            f"{exit_price:.1f}"
        )

        print(
            f"   PnL: "
            f"{pnl_percent:+.2f}%"
        )

        print(
            f"   Hold: "
            f"{holding_hours:.1f}ч"
        )

    # ========================================================
    # BACKTEST
    # ========================================================

    def run(self):

        print()
        print("=" * 80)
        print(
            "📊 TAURUS BACKTEST"
        )
        print("=" * 80)

        print(
            f"SL: "
            f"{self.config.sl_points} points"
        )

        print(
            f"TP: НЕТ"
        )

        print(
            f"Exit: TREND EXHAUSTION"
        )

        print(
            f"Leverage: "
            f"{self.config.leverage}x"
        )

        print(
            "Zones: OFF"
        )

        print(
            "Reverse: OFF"
        )

        print("=" * 80)

        i = 1

        while i < len(self.data) - 1:

            current = self.data[i]

            signal = self.get_signal(i)

            self.total_decisions += 1

            # ------------------------------------------------
            # PRINT DECISION
            # ------------------------------------------------

            print()
            print(
                f"🕐 "
                f"{current.timestamp} "
                f"@ {current.close_price:.1f}"
            )

            print(
                f"   "
                f"Price: "
                f"{current.price_change:+.3f}% "
                f"(median "
                f"{self.price_median:.3f}%)"
            )

            print(
                f"   "
                f"Volume: "
                f"{current.volume_ratio:.2f}x median"
            )

            print(
                f"   "
                f"OI: "
                f"{current.oi_change:+.3f}% "
                f"(median "
                f"{self.oi_median:.3f}%)"
            )

            print(
                f"   "
                f"TakerBuy: "
                f"{current.taker_buy:.1f}%"
            )

            print(
                f"   "
                f"Score: "
                f"L={signal.score_long} "
                f"S={signal.score_short}"
            )

            print(
                f"   "
                f"Decision: "
                f"{signal.direction}"
            )

            # ------------------------------------------------
            # NO TRADE
            # ------------------------------------------------

            if signal.direction == "FLAT":

                self.no_trade += 1

                i += 1

                continue

            # ------------------------------------------------
            # OPEN
            # ------------------------------------------------

            entry_price = (
                current.close_price
            )

            if signal.direction == "LONG":

                sl_price = (
                    entry_price
                    -
                    self.config.sl_points
                )

            else:

                sl_price = (
                    entry_price
                    +
                    self.config.sl_points
                )

            trade = Trade(

                trade_number=
                    len(self.trades) + 1,

                entry_time=
                    current.timestamp.isoformat(),

                entry_price=
                    entry_price,

                direction=
                    signal.direction,

                confidence=
                    signal.confidence,

                score_long=
                    signal.score_long,

                score_short=
                    signal.score_short,

                entry_reasons=
                    signal.confirmations.copy(),

                sl_price=
                    sl_price
            )

            print()
            print(
                "🟢 ОТКРЫТИЕ"
            )

            print(
                f"   "
                f"#{trade.trade_number} "
                f"{trade.direction}"
            )

            print(
                f"   Entry: "
                f"{entry_price:.1f}"
            )

            print(
                f"   SL: "
                f"{sl_price:.1f}"
            )

            print(
                f"   Score: "
                f"L={signal.score_long} "
                f"S={signal.score_short}"
            )

            print(
                f"   "
                f"{signal.confidence} "
                f"| "
                f"{signal.trend_state}"
            )

            print(
                f"   "
                f"Reasons: "
                f"{', '.join(signal.confirmations)}"
            )

            # ------------------------------------------------
            # HOLD
            # ------------------------------------------------

            j = i + 1

            closed = False

            while j < len(self.data):

                candle = self.data[j]

                # ------------------------------------------------
                # MFE / MAE
                # ------------------------------------------------

                if trade.direction == "LONG":

                    favorable = (
                        candle.high
                        -
                        trade.entry_price
                    )

                    adverse = (
                        candle.low
                        -
                        trade.entry_price
                    )

                else:

                    favorable = (
                        trade.entry_price
                        -
                        candle.low
                    )

                    adverse = (
                        trade.entry_price
                        -
                        candle.high
                    )

                trade.max_favorable_points = max(
                    trade.max_favorable_points,
                    favorable
                )

                trade.max_adverse_points = min(
                    trade.max_adverse_points,
                    adverse
                )

                # ------------------------------------------------
                # SL FIRST
                # ------------------------------------------------

                if self.check_sl(
                    trade,
                    candle
                ):

                    self.close_trade(
                        trade,
                        candle,
                        "SL",
                        trade.sl_price
                    )

                    i = j + 1

                    closed = True

                    break

                # ------------------------------------------------
                # HOLD TIME
                # ------------------------------------------------

                entry_time = datetime.fromisoformat(
                    trade.entry_time
                )

                holding_hours = (
                    candle.timestamp -
                    entry_time
                ).total_seconds() / 3600

                # ------------------------------------------------
                # MAX TIME SAFETY
                # ------------------------------------------------

                if (
                    holding_hours
                    >= self.config.max_hold_hours
                ):

                    self.close_trade(
                        trade,
                        candle,
                        "MAX_HOLD",
                        candle.close_price
                    )

                    i = j + 1

                    closed = True

                    break

                # ------------------------------------------------
                # DON'T EXIT TOO EARLY
                # ------------------------------------------------

                if (
                    holding_hours
                    >= self.config.min_hold_hours
                ):

                    exhausted, reasons = (
                        self.check_exhaustion(
                            trade,
                            j
                        )
                    )

                    if exhausted:

                        print(
                            f"   🔥 "
                            f"TREND EXHAUSTED:"
                        )

                        print(
                            f"      "
                            f"{', '.join(reasons)}"
                        )

                        self.close_trade(
                            trade,
                            candle,
                            "TREND_EXHAUSTION",
                            candle.close_price
                        )

                        i = j + 1

                        closed = True

                        break

                j += 1

            # ------------------------------------------------
            # END OF DATA
            # ------------------------------------------------

            if not closed:

                last = self.data[-1]

                self.close_trade(
                    trade,
                    last,
                    "END_OF_DATA",
                    last.close_price
                )

                break

    # ========================================================
    # STATISTICS
    # ========================================================

    def statistics(self):

        print()
        print("=" * 80)
        print(
            "📊 ИТОГОВАЯ СТАТИСТИКА"
        )
        print("=" * 80)

        total = len(self.trades)

        print(
            f"Решений: "
            f"{self.total_decisions}"
        )

        print(
            f"NO TRADE: "
            f"{self.no_trade}"
        )

        print(
            f"Сделок: "
            f"{total}"
        )

        if not total:

            print(
                "❌ Сделок нет"
            )

            return

        wins = sum(
            1
            for t in self.trades
            if t.pnl_percent > 0
        )

        losses = total - wins

        sl_count = sum(
            1
            for t in self.trades
            if t.result == "SL"
        )

        exhaustion_count = sum(
            1
            for t in self.trades
            if t.result ==
            "TREND_EXHAUSTION"
        )

        max_hold_count = sum(
            1
            for t in self.trades
            if t.result ==
            "MAX_HOLD"
        )

        total_pnl = sum(
            t.pnl_percent
            for t in self.trades
        )

        avg_pnl = (
            total_pnl / total
        )

        avg_hold = (
            sum(
                t.holding_hours
                for t in self.trades
            )
            /
            total
        )

        print()

        print(
            f"WIN: "
            f"{wins} "
            f"({wins / total * 100:.1f}%)"
        )

        print(
            f"LOSS: "
            f"{losses} "
            f"({losses / total * 100:.1f}%)"
        )

        print()

        print(
            f"SL: "
            f"{sl_count}"
        )

        print(
            f"TREND EXHAUSTION: "
            f"{exhaustion_count}"
        )

        print(
            f"MAX HOLD: "
            f"{max_hold_count}"
        )

        print()

        print(
            f"💰 Total PnL: "
            f"{total_pnl:+.2f}%"
        )

        print(
            f"Average PnL: "
            f"{avg_pnl:+.2f}%"
        )

        print(
            f"Average holding: "
            f"{avg_hold:.1f}ч"
        )

        print()
        print("=" * 80)

    # ========================================================
    # SAVE
    # ========================================================

    def save(
        self,
        filename="backtest_results.json"
    ):

        result = {

            "config":
                asdict(self.config),

            "medians": {

                "volume":
                    self.volume_median,

                "oi":
                    self.oi_median,

                "price":
                    self.price_median
            },

            "strategy": {

                "zones":
                    False,

                "reverse":
                    False,

                "static_sl":
                    True,

                "static_tp":
                    False,

                "dynamic_exit":
                    "trend_exhaustion"
            },

            "statistics": {

                "decisions":
                    self.total_decisions,

                "no_trade":
                    self.no_trade,

                "trades":
                    len(self.trades),

                "wins":
                    sum(
                        1
                        for t in self.trades
                        if t.pnl_percent > 0
                    ),

                "losses":
                    sum(
                        1
                        for t in self.trades
                        if t.pnl_percent <= 0
                    ),

                "total_pnl_percent":
                    round(
                        sum(
                            t.pnl_percent
                            for t in self.trades
                        ),
                        4
                    )
            },

            "trades": [

                asdict(t)

                for t in self.trades
            ]
        }

        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                result,
                f,
                indent=2,
                ensure_ascii=False
            )

        print()
        print(
            f"✅ Результаты сохранены: "
            f"{filename}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    config = Config(

        leverage=10,

        sl_points=300,

        commission_pct=0.04,

        slippage_pct=0.02,

        # ----------------------------------------------------
        # SIGNAL
        # ----------------------------------------------------

        min_confirmations=2,

        strong_confirmations=4,

        # ----------------------------------------------------
        # MEDIAN
        # ----------------------------------------------------

        volume_normal=1.0,

        volume_strong=2.0,

        volume_extreme=3.0,

        price_normal=1.0,

        price_strong=1.5,

        oi_normal=1.0,

        oi_strong=1.5,

        # ----------------------------------------------------
        # TAKER
        # ----------------------------------------------------

        taker_neutral_low=48,

        taker_neutral_high=52,

        taker_long=53,

        taker_strong_long=55,

        taker_short=47,

        taker_strong_short=45,

        # ----------------------------------------------------
        # EXIT
        # ----------------------------------------------------

        min_hold_hours=2,

        exhaustion_confirmations=2,

        stagnation_multiplier=0.5,

        max_hold_hours=48
    )

    backtest = TaurusBacktest(
        "taurus_x_container.log",
        config
    )

    backtest.parse_log()

    if not backtest.data:

        print(
            "❌ Нет данных для тестирования"
        )

        return

    backtest.run()

    backtest.statistics()

    backtest.save()


if __name__ == "__main__":

    main()