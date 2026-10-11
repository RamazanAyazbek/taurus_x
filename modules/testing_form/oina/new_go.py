import re
import json
import math
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Optional


# ============================================================
# CONFIGURATION
# ============================================================

LOG_FILE = "taurus_x_container.log"
RESULT_FILE = "backtest_results.json"


@dataclass
class Config:
    # -------------------------
    # Risk
    # -------------------------
    sl_points: float = 500.0
    leverage: float = 10.0

    # -------------------------
    # ENTRY
    # -------------------------

    # Не слишком высокий порог.
    # Алгоритм может войти даже при умеренном сигнале,
    # если несколько факторов смотрят в одну сторону.
    min_entry_score: float = 2.00

    # Насколько один direction должен превосходить другой.
    min_score_margin: float = 0.45

    # Максимум одновременно одной позиции.
    one_position_only: bool = True

    # -------------------------
    # PATH
    # -------------------------

    path_hours_short: int = 3
    path_hours_medium: int = 6
    path_hours_long: int = 12

    # -------------------------
    # EXIT
    # -------------------------

    # Сколько последовательных часов ухудшения
    # нужно для выхода.
    exhaustion_confirmations: int = 2

    # Насколько сильным должно быть противоположное
    # движение для немедленного выхода.
    reversal_score: float = 2.5

    # Минимальное количество часов позиции,
    # чтобы не закрывать её слишком рано только
    # из-за шума.
    min_hold_hours: int = 1


CONFIG = Config()


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class Baseline:
    timestamp: datetime
    volume_median: float
    oi_median: float
    price_median: float


@dataclass
class HourData:
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
    long_score: float
    short_score: float
    confidence: float

    components: Dict[str, float]
    explanation: List[str]


@dataclass
class Position:
    direction: str

    entry_time: datetime
    entry_price: float

    sl_price: float

    highest_price: float
    lowest_price: float

    hold_hours: int = 0

    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None

    pnl_points: float = 0.0
    pnl_percent: float = 0.0
    leveraged_pnl_percent: float = 0.0


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sign(value: float) -> float:
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0


def safe_ratio(value: float, median: float) -> float:
    if median <= 0:
        return 0.0
    return value / median


# ============================================================
# PARSER
# ============================================================

class TaurusLogParser:

    BASELINE_RE = re.compile(
        r"Period:.*?\n"
        r".*?Volume Median:\s*([\d.]+)"
        r"\s*\|\s*dOI Median:\s*([\d.]+)%"
        r"\s*\|\s*dPrice Median:\s*([\d.]+)%",
        re.MULTILINE
    )

    # Старый / универсальный вариант:
    #
    # ⏰ ИТОГ ЧАСА (14:00): BULLISH |
    # Изм: +0.14% (62908.6 -> 62999.1) |
    # Range: [62890.2 - 63019.9] | Vol: 1726

    HOUR_RE = re.compile(
        r"(?P<date>\d{4}-\d{2}-\d{2}).*?"
        r"⏰ ИТОГ ЧАСА"
        r"(?: \[[^\]]+\]|\s*)"
        r"\s*\((?P<time>\d{2}:\d{2})\)"
        r"[^:]*:\s*"
        r"(?P<sentiment>[^\|]+)"
        r"\|\s*Изм:\s*(?P<price_change>[+-]?[\d.]+)%"
        r"\s*\((?P<open>[\d.]+)\s*->\s*(?P<close>[\d.]+)\)"
        r"\s*\|\s*Range:\s*\[(?P<low>[\d.]+)\s*-\s*(?P<high>[\d.]+)\]"
        r"\s*\|\s*Vol:\s*(?P<volume>[\d.]+)",
        re.MULTILINE
    )

    # Новый вариант:
    #
    # ⏰ ИТОГ ЧАСА [22:00-59]: BULLISH |
    # Изм: +0.57% (...) |
    # H/L ... | dOI: +0.17% (0.97x Med) |
    # Vol: 8648 (1.98x Med) | TakerBuy: 61.7%

    HOUR_NEW_RE = re.compile(
        r"(?P<date>\d{4}-\d{2}-\d{2}).*?"
        r"⏰ ИТОГ ЧАСА\s+\[(?P<time>\d{2}):\d{2}-\d{2}\]"
        r"\s*:\s*(?P<sentiment>[^\|]+)"
        r"\|\s*Изм:\s*(?P<price_change>[+-]?[\d.]+)%"
        r"\s*\((?P<open>[\d.]+)\s*->\s*(?P<close>[\d.]+)\)"
        r"\s*\|\s*"
        r"(?:📊\s*)?"
        r"\[H:(?P<high>[\d.]+)\s*\|\s*L:(?P<low>[\d.]+)\]"
        r"\s*\|\s*dOI:\s*(?P<oi>[+-]?[\d.]+)%"
        r".*?\|\s*Vol:\s*(?P<volume>[\d.]+)"
        r".*?\|\s*TakerBuy:\s*(?P<taker>[\d.]+)%",
        re.MULTILINE
    )

    def __init__(self, path: str):
        self.path = path
        self.baselines: List[Baseline] = []
        self.hours: List[HourData] = []

    def parse(self):
        print("🔍 Парсинг taurus_x_container.log...")

        with open(self.path, "r", encoding="utf-8") as f:
            content = f.read()

        self._parse_baselines(content)
        self._parse_hours(content)

        self.hours.sort(key=lambda x: x.timestamp)

        # Удаляем возможные дубликаты.
        unique = {}

        for item in self.hours:
            unique[item.timestamp] = item

        self.hours = list(unique.values())
        self.hours.sort(key=lambda x: x.timestamp)

        print(f"✅ Baselines: {len(self.baselines)}")
        print(f"✅ Найдено {len(self.hours)} часовых данных")

    # --------------------------------------------------------
    # BASELINES
    # --------------------------------------------------------

    def _parse_baselines(self, content: str):

        for match in self.BASELINE_RE.finditer(content):

            date_match = re.search(
                r"(\d{4}-\d{2}-\d{2})",
                content[max(0, match.start() - 100):match.start()]
            )

            if not date_match:
                continue

            date = date_match.group(1)

            try:
                timestamp = datetime.strptime(
                    date,
                    "%Y-%m-%d"
                )

                self.baselines.append(
                    Baseline(
                        timestamp=timestamp,
                        volume_median=float(match.group(1)),
                        oi_median=float(match.group(2)),
                        price_median=float(match.group(3)),
                    )
                )

            except Exception:
                continue

        self.baselines.sort(key=lambda x: x.timestamp)

    # --------------------------------------------------------
    # FIND BASELINE FOR HOUR
    # --------------------------------------------------------

    def _get_baseline(self, timestamp: datetime) -> Baseline:

        selected = None

        for baseline in self.baselines:

            if baseline.timestamp <= timestamp:
                selected = baseline

            else:
                break

        if selected:
            return selected

        # Fallback из твоего лога
        return Baseline(
            timestamp=timestamp,
            volume_median=4377.9,
            oi_median=0.177,
            price_median=0.167,
        )

    # --------------------------------------------------------
    # HOURLY DATA
    # --------------------------------------------------------

    def _parse_hours(self, content: str):

        # Новый формат
        for match in self.HOUR_NEW_RE.finditer(content):

            try:

                timestamp = datetime.strptime(
                    f"{match.group('date')} {match.group('time')}",
                    "%Y-%m-%d %H:%M"
                )

                sentiment = match.group("sentiment").strip()

                hour = HourData(
                    timestamp=timestamp,

                    open_price=float(match.group("open")),
                    close_price=float(match.group("close")),
                    high=float(match.group("high")),
                    low=float(match.group("low")),

                    price_change=float(match.group("price_change")),

                    oi_change=float(match.group("oi")),

                    volume=float(match.group("volume")),

                    volume_ratio=0.0,

                    taker_buy=float(match.group("taker")),

                    sentiment=sentiment,
                )

                baseline = self._get_baseline(timestamp)

                hour.volume_ratio = safe_ratio(
                    hour.volume,
                    baseline.volume_median
                )

                self.hours.append(hour)

            except Exception:
                continue

        # Старый формат
        for match in self.HOUR_RE.finditer(content):

            try:

                timestamp = datetime.strptime(
                    f"{match.group('date')} {match.group('time')}",
                    "%Y-%m-%d %H:%M"
                )

                # Если уже нашли новый формат — не добавляем дубль.
                if any(x.timestamp == timestamp for x in self.hours):
                    continue

                baseline = self._get_baseline(timestamp)

                hour = HourData(
                    timestamp=timestamp,

                    open_price=float(match.group("open")),
                    close_price=float(match.group("close")),
                    high=float(match.group("high")),
                    low=float(match.group("low")),

                    price_change=float(match.group("price_change")),

                    oi_change=0.0,

                    volume=float(match.group("volume")),

                    volume_ratio=safe_ratio(
                        float(match.group("volume")),
                        baseline.volume_median
                    ),

                    taker_buy=50.0,

                    sentiment=match.group("sentiment").strip(),
                )

                self.hours.append(hour)

            except Exception:
                continue


# ============================================================
# TAURUS ENGINE
# ============================================================

class TaurusEngine:

    """
    Главный алгоритм.

    ВАЖНО:

    Никаких:
        if X > 3: LONG
        if Y < -0.2: SHORT

    Здесь каждый фактор даёт вклад.

    Итог:

        LONG SCORE
        SHORT SCORE

    Потом сравниваем их.

    Благодаря этому добавление нового фактора
    не ломает основной алгоритм.
    """

    def __init__(self, config: Config):
        self.config = config

    # ========================================================
    # PUBLIC ENTRY
    # ========================================================

    def analyze_entry(
        self,
        data: List[HourData],
        index: int
    ) -> Signal:

        current = data[index]

        if index < 2:
            return Signal(
                direction="WAIT",
                long_score=0,
                short_score=0,
                confidence=0,
                components={},
                explanation=["Недостаточно истории"]
            )

        history = data[:index + 1]

        components = {}

        # ----------------------------------------------------
        # 1. CURRENT PRICE MOMENTUM
        # ----------------------------------------------------

        current_price_score = self._price_momentum(history)

        components["price_momentum"] = current_price_score

        # ----------------------------------------------------
        # 2. PATH
        # ----------------------------------------------------

        path_score = self._price_path(history)

        components["price_path"] = path_score

        # ----------------------------------------------------
        # 3. TREND PERSISTENCE
        # ----------------------------------------------------

        persistence_score = self._trend_persistence(history)

        components["persistence"] = persistence_score

        # ----------------------------------------------------
        # 4. VOLUME
        # ----------------------------------------------------

        volume_score = self._volume_confirmation(current)

        components["volume"] = volume_score

        # ----------------------------------------------------
        # 5. OI
        # ----------------------------------------------------

        oi_score = self._oi_confirmation(current)

        components["oi"] = oi_score

        # ----------------------------------------------------
        # 6. TAKER BUY
        # ----------------------------------------------------

        taker_score = self._taker_confirmation(current)

        components["taker"] = taker_score

        # ----------------------------------------------------
        # 7. SENTIMENT
        # ----------------------------------------------------

        sentiment_score = self._sentiment_score(current)

        components["sentiment"] = sentiment_score

        # ----------------------------------------------------
        # 8. ACCELERATION
        # ----------------------------------------------------

        acceleration_score = self._acceleration(history)

        components["acceleration"] = acceleration_score

        # ----------------------------------------------------
        # 9. WEIGHTED TOTAL
        # ----------------------------------------------------

        long_score = 0.0
        short_score = 0.0

        for name, score in components.items():

            # score:
            #
            # positive = LONG
            # negative = SHORT

            if score > 0:
                long_score += score
            elif score < 0:
                short_score += abs(score)

        # ----------------------------------------------------
        # Decision
        # ----------------------------------------------------

        difference = abs(long_score - short_score)

        if (
            max(long_score, short_score)
            < self.config.min_entry_score
        ):
            direction = "WAIT"

        elif difference < self.config.min_score_margin:
            direction = "WAIT"

        elif long_score > short_score:
            direction = "LONG"

        else:
            direction = "SHORT"

        total = long_score + short_score

        confidence = (
            difference / total
            if total > 0
            else 0
        )

        confidence = clamp(confidence, 0, 1)

        explanation = self._build_explanation(
            components,
            direction
        )

        return Signal(
            direction=direction,
            long_score=round(long_score, 4),
            short_score=round(short_score, 4),
            confidence=round(confidence, 4),
            components={
                k: round(v, 4)
                for k, v in components.items()
            },
            explanation=explanation
        )

    # ========================================================
    # PRICE MOMENTUM
    # ========================================================

    def _price_momentum(
        self,
        history: List[HourData]
    ) -> float:

        current = history[-1]

        # Последний час
        p1 = current.price_change

        # Нормализуем относительно медианы dPrice.
        # Берём baseline непосредственно из самого лога.
        #
        # Здесь медиана примерно 0.167%, поэтому
        # +0.5% уже заметное движение,
        # +2% — экстремальное.

        normalized = p1 / 0.167

        return clamp(normalized * 0.35, -1.2, 1.2)

    # ========================================================
    # PRICE PATH
    # ========================================================

    def _price_path(
        self,
        history: List[HourData]
    ) -> float:

        if len(history) < 3:
            return 0.0

        short = history[-self.config.path_hours_short:]

        medium = history[-self.config.path_hours_medium:]

        long = history[-self.config.path_hours_long:]

        short_change = (
            short[-1].close_price - short[0].open_price
        ) / short[0].open_price * 100

        medium_change = (
            medium[-1].close_price - medium[0].open_price
        ) / medium[0].open_price * 100

        long_change = (
            long[-1].close_price - long[0].open_price
        ) / long[0].open_price * 100

        # Weighted path.
        #
        # Ближняя история важнее,
        # но более длинный путь тоже учитывается.

        score = (
            short_change * 0.65
            + medium_change * 0.30
            + long_change * 0.15
        )

        # Нормализация.
        score /= 0.35

        return clamp(score, -1.8, 1.8)

    # ========================================================
    # TREND PERSISTENCE
    # ========================================================

    def _trend_persistence(
        self,
        history: List[HourData]
    ) -> float:

        if len(history) < 3:
            return 0.0

        window = history[-6:]

        directional = 0

        total_weight = 0

        for i, candle in enumerate(window):

            weight = i + 1

            if candle.price_change > 0:
                directional += weight

            elif candle.price_change < 0:
                directional -= weight

            total_weight += weight

        if total_weight == 0:
            return 0.0

        persistence = directional / total_weight

        return persistence * 1.5

    # ========================================================
    # VOLUME
    # ========================================================

    def _volume_confirmation(
        self,
        current: HourData
    ) -> float:

        ratio = current.volume_ratio

        # Не жёсткий порог.
        #
        # 0.5x -> почти нет подтверждения
        # 1x   -> нормальный
        # 2x   -> хороший
        # 5x+  -> очень сильный

        strength = math.log1p(max(ratio, 0))

        strength = clamp(
            strength / math.log1p(6),
            0,
            1
        )

        direction = sign(current.price_change)

        return direction * strength * 1.35

    # ========================================================
    # OI
    # ========================================================

    def _oi_confirmation(
        self,
        current: HourData
    ) -> float:

        oi = current.oi_change

        # dOI относительно типичного масштаба.
        normalized = oi / 0.177

        strength = clamp(
            abs(normalized),
            0,
            3
        )

        # OI + price +:
        #
        # Цена растёт + OI растёт
        # → движение подтверждается.
        #
        # Цена падает + OI растёт
        # → тоже может подтверждать SHORT.
        #
        # Если OI падает при сильном движении,
        # это может быть squeeze/liquidation,
        # поэтому здесь НЕ делаем автоматический reverse.

        direction = sign(current.price_change)

        return direction * clamp(
            strength * 0.30,
            -0.9,
            0.9
        )

    # ========================================================
    # TAKER BUY
    # ========================================================

    def _taker_confirmation(
        self,
        current: HourData
    ) -> float:

        # 50 = нейтраль.
        #
        # 60 = умеренное преимущество покупателей.
        # 70 = сильное.
        #
        # 40 = умеренное преимущество продавцов.

        imbalance = (
            current.taker_buy - 50
        ) / 10

        return clamp(
            imbalance * 0.25,
            -0.8,
            0.8
        )

    # ========================================================
    # SENTIMENT
    # ========================================================

    def _sentiment_score(
        self,
        current: HourData
    ) -> float:

        text = current.sentiment.upper()

        if "BULL" in text:
            return 0.35

        if "BEAR" in text:
            return -0.35

        return 0.0

    # ========================================================
    # ACCELERATION
    # ========================================================

    def _acceleration(
        self,
        history: List[HourData]
    ) -> float:

        if len(history) < 3:
            return 0.0

        a = history[-3].price_change
        b = history[-2].price_change
        c = history[-1].price_change

        # Изменение импульса.
        acceleration = (
            (b - a)
            + (c - b)
        )

        return clamp(
            acceleration / 0.25,
            -1.0,
            1.0
        )

    # ========================================================
    # EXPLANATION
    # ========================================================

    def _build_explanation(
        self,
        components: Dict[str, float],
        direction: str
    ) -> List[str]:

        result = []

        sorted_components = sorted(
            components.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )

        for name, value in sorted_components[:5]:

            if abs(value) < 0.05:
                continue

            side = "LONG" if value > 0 else "SHORT"

            result.append(
                f"{name}: {side} {abs(value):.2f}"
            )

        if not result:
            result.append("Недостаточно выраженного преимущества")

        return result

    # ========================================================
    # POSITION MANAGEMENT
    # ========================================================

    def update_position(
        self,
        position: Position,
        history: List[HourData],
        current_index: int
    ) -> Optional[Dict]:

        current = history[current_index]

        position.hold_hours += 1

        position.highest_price = max(
            position.highest_price,
            current.high
        )

        position.lowest_price = min(
            position.lowest_price,
            current.low
        )

        # ----------------------------------------------------
        # 1. STOP LOSS
        # ----------------------------------------------------

        if position.direction == "LONG":

            if current.low <= position.sl_price:

                return self._close_position(
                    position,
                    current.timestamp,
                    position.sl_price,
                    "SL"
                )

        else:

            if current.high >= position.sl_price:

                return self._close_position(
                    position,
                    current.timestamp,
                    position.sl_price,
                    "SL"
                )

        # ----------------------------------------------------
        # 2. EXHAUSTION
        # ----------------------------------------------------

        if position.hold_hours >= self.config.min_hold_hours:

            exit_signal = self._check_exhaustion(
                position,
                history,
                current_index
            )

            if exit_signal:

                return self._close_position(
                    position,
                    current.timestamp,
                    current.close_price,
                    exit_signal
                )

        return None

    # ========================================================
    # EXHAUSTION
    # ========================================================

    def _check_exhaustion(
        self,
        position: Position,
        history: List[HourData],
        index: int
    ) -> Optional[str]:

        if index < 2:
            return None

        recent = history[
            max(0, index - 2):index + 1
        ]

        adverse_count = 0

        for candle in recent:

            if position.direction == "LONG":

                # Цена идёт против позиции.
                if candle.price_change < -0.10:
                    adverse_count += 1

            else:

                if candle.price_change > 0.10:
                    adverse_count += 1

        if (
            adverse_count
            >= self.config.exhaustion_confirmations
        ):

            return "TREND_EXHAUSTION"

        # ----------------------------------------------------
        # Сильный противоположный импульс
        # ----------------------------------------------------

        current = history[index]

        opposite_score = self.analyze_entry(
            history,
            index
        )

        if position.direction == "LONG":

            if (
                opposite_score.direction == "SHORT"
                and opposite_score.short_score
                >= self.config.reversal_score
            ):
                return "STRONG_REVERSAL"

        else:

            if (
                opposite_score.direction == "LONG"
                and opposite_score.long_score
                >= self.config.reversal_score
            ):
                return "STRONG_REVERSAL"

        return None

    # ========================================================
    # CLOSE
    # ========================================================

    def _close_position(
        self,
        position: Position,
        timestamp: datetime,
        price: float,
        reason: str
    ) -> Dict:

        position.exit_time = timestamp
        position.exit_price = price
        position.exit_reason = reason

        if position.direction == "LONG":

            position.pnl_points = (
                price - position.entry_price
            )

        else:

            position.pnl_points = (
                position.entry_price - price
            )

        position.pnl_percent = (
            position.pnl_points
            / position.entry_price
            * 100
        )

        position.leveraged_pnl_percent = (
            position.pnl_percent
            * CONFIG.leverage
        )

        return asdict(position)


# ============================================================
# BACKTEST
# ============================================================

class Backtester:

    def __init__(
        self,
        data: List[HourData],
        engine: TaurusEngine
    ):

        self.data = data
        self.engine = engine

        self.trades = []
        self.signals = []

    # ========================================================
    # RUN
    # ========================================================

    def run(self):

        position: Optional[Position] = None

        print()
        print("=" * 80)
        print("📊 TAURUS BACKTEST")
        print("=" * 80)
        print(f"SL: {CONFIG.sl_points} points")
        print(f"Leverage: {CONFIG.leverage}x")
        print("TP: DYNAMIC")
        print("Zones: OFF")
        print("Reverse: OFF")
        print("=" * 80)

        for i in range(1, len(self.data)):

            current = self.data[i]

            # =================================================
            # POSITION
            # =================================================

            if position:

                result = self.engine.update_position(
                    position,
                    self.data,
                    i
                )

                if result:

                    self.trades.append(result)

                    self._print_trade(result)

                    position = None

                    # Важно:
                    # после закрытия НЕ открываем новый ордер
                    # на той же самой цене.
                    continue

                continue

            # =================================================
            # ENTRY
            # =================================================

            signal = self.engine.analyze_entry(
                self.data,
                i
            )

            self.signals.append({
                "timestamp": current.timestamp.isoformat(),
                "price": current.close_price,
                "direction": signal.direction,
                "long_score": signal.long_score,
                "short_score": signal.short_score,
                "confidence": signal.confidence,
                "components": signal.components,
                "explanation": signal.explanation,
            })

            if signal.direction == "WAIT":
                continue

            # -------------------------------------------------
            # OPEN
            # -------------------------------------------------

            entry_price = current.close_price

            if signal.direction == "LONG":

                sl = (
                    entry_price
                    - CONFIG.sl_points
                )

                position = Position(
                    direction="LONG",
                    entry_time=current.timestamp,
                    entry_price=entry_price,
                    sl_price=sl,
                    highest_price=entry_price,
                    lowest_price=entry_price,
                )

            else:

                sl = (
                    entry_price
                    + CONFIG.sl_points
                )

                position = Position(
                    direction="SHORT",
                    entry_time=current.timestamp,
                    entry_price=entry_price,
                    sl_price=sl,
                    highest_price=entry_price,
                    lowest_price=entry_price,
                )

            self._print_entry(
                position,
                signal
            )

        # =====================================================
        # FORCE CLOSE LAST POSITION
        # =====================================================

        if position:

            last = self.data[-1]

            result = self.engine._close_position(
                position,
                last.timestamp,
                last.close_price,
                "END_OF_DATA"
            )

            self.trades.append(result)

            print()
            print(
                f"⚠️ Последняя сделка закрыта "
                f"по последней доступной цене: "
                f"{last.close_price}"
            )

    # ========================================================
    # PRINT ENTRY
    # ========================================================

    def _print_entry(
        self,
        position: Position,
        signal: Signal
    ):

        icon = (
            "🟢"
            if position.direction == "LONG"
            else "🔴"
        )

        print()
        print(
            f"{icon} OPEN {position.direction}"
        )

        print(
            f"   Вход: "
            f"{position.entry_time} "
            f"@ {position.entry_price:.2f}"
        )

        print(
            f"   SL: {position.sl_price:.2f}"
        )

        print(
            f"   Score: "
            f"L={signal.long_score:.2f} "
            f"S={signal.short_score:.2f}"
        )

        print(
            f"   Confidence: "
            f"{signal.confidence:.1%}"
        )

        if signal.explanation:

            print(
                "   Причины: "
                + " | ".join(signal.explanation)
            )

    # ========================================================
    # PRINT TRADE
    # ========================================================

    def _print_trade(
        self,
        trade: Dict
    ):

        pnl = trade["leveraged_pnl_percent"]

        icon = "✅" if pnl >= 0 else "❌"

        print(
            f"{icon} CLOSE "
            f"{trade['direction']} "
            f"@ {trade['exit_price']:.2f} "
            f"| {trade['exit_reason']} "
            f"| PnL: {pnl:+.2f}% "
            f"| {trade['hold_hours']}h"
        )

    # ========================================================
    # RESULTS
    # ========================================================

    def summary(self):

        total = len(self.trades)

        if total == 0:

            print()
            print("❌ Сделок нет")

            return

        wins = [
            x for x in self.trades
            if x["pnl_points"] > 0
        ]

        losses = [
            x for x in self.trades
            if x["pnl_points"] <= 0
        ]

        total_pnl = sum(
            x["leveraged_pnl_percent"]
            for x in self.trades
        )

        avg_pnl = (
            total_pnl / total
        )

        print()
        print("=" * 80)
        print("📊 ИТОГОВАЯ СТАТИСТИКА")
        print("=" * 80)

        print(
            f"Часовых данных: "
            f"{len(self.data)}"
        )

        print(
            f"Сигналов: "
            f"{len(self.signals)}"
        )

        print(
            f"Сделок: "
            f"{total}"
        )

        print(
            f"Прибыльных: "
            f"{len(wins)} "
            f"({len(wins)/total:.1%})"
        )

        print(
            f"Убыточных: "
            f"{len(losses)} "
            f"({len(losses)/total:.1%})"
        )

        print()

        print(
            f"Общий PnL: "
            f"{total_pnl:+.2f}%"
        )

        print(
            f"Средний PnL сделки: "
            f"{avg_pnl:+.2f}%"
        )

        if wins:

            print(
                f"Средняя прибыль: "
                f"{sum(x['leveraged_pnl_percent'] for x in wins)/len(wins):+.2f}%"
            )

        if losses:

            print(
                f"Средний убыток: "
                f"{sum(x['leveraged_pnl_percent'] for x in losses)/len(losses):+.2f}%"
            )

        print()

        long_trades = [
            x for x in self.trades
            if x["direction"] == "LONG"
        ]

        short_trades = [
            x for x in self.trades
            if x["direction"] == "SHORT"
        ]

        print(
            f"LONG: "
            f"{len(long_trades)}"
        )

        print(
            f"SHORT: "
            f"{len(short_trades)}"
        )

        print()

        reasons = {}

        for trade in self.trades:

            reason = trade["exit_reason"]

            reasons[reason] = (
                reasons.get(reason, 0) + 1
            )

        print("Причины закрытия:")

        for reason, count in reasons.items():

            print(
                f"  {reason}: {count}"
            )

        print("=" * 80)


# ============================================================
# SAVE
# ============================================================

def save_results(
    parser: TaurusLogParser,
    backtester: Backtester
):

    output = {

        "config": asdict(CONFIG),

        "data": {
            "hours": len(parser.hours),
            "first_timestamp": (
                parser.hours[0].timestamp.isoformat()
                if parser.hours
                else None
            ),
            "last_timestamp": (
                parser.hours[-1].timestamp.isoformat()
                if parser.hours
                else None
            ),
        },

        "trades": backtester.trades,

        "signals": backtester.signals,
    }

    with open(
        RESULT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            indent=2,
            ensure_ascii=False,
            default=str
        )

    print()
    print(
        f"✅ Результаты записаны: "
        f"{RESULT_FILE}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("🚀 TAURUS BACKTEST ENGINE")
    print()

    parser = TaurusLogParser(
        LOG_FILE
    )

    parser.parse()

    if len(parser.hours) < 10:

        print(
            "❌ Недостаточно часовых данных "
            "для backtest"
        )

        return

    engine = TaurusEngine(
        CONFIG
    )

    backtester = Backtester(
        parser.hours,
        engine
    )

    backtester.run()

    backtester.summary()

    save_results(
        parser,
        backtester
    )


if __name__ == "__main__":
    main()

