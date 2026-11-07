# Taurus SHORT v4 — confirmation TakerBuy filter experiment.
SYMBOL = "BTCUSDT"
LOG_FILE = "data/taurus_x_container.log"
RESULTS_DIR = "results"
RESULT_PREFIX = "short"
STRATEGY_VERSION = "v7.4.ch.1.1filter"

# Keep the Long project's TP/SL, fee model, and timeout logic.
TP_PCT = 1.5
SL_PCT = 0.7
TIMEOUT_MINUTES = 1080
TAKER_FEE = 0.05
MAKER_FEE = 0.02
ENABLE_FEES = True
ENABLE_STATE_LOCK = True

# Wait for the next Taurus monitoring observation before entry.
# If price has bounced too far upward against the SHORT idea, cancel it.
# If confirmed, the simulator enters at the next observation's price/time.
ENTRY_CONFIRMATION_ENABLED = True
CONFIRMATION_MAX_GAP_MINUTES = 20
CONFIRMATION_MAX_REBOUND_PCT = 0.25

# New v4 filter: at confirmation, require TakerBuy >= this threshold.
# Hypothesis: avoid chasing a sell impulse when aggressive selling dominates.
# Exploratory only; validate on fresh periods before using live.
CONFIRMATION_MIN_TAKER_BUY = 42.0

# Base SHORT-entry filters.
MIN_VOLUME_XMED = 1.5
MIN_DOI_XMED = 0.0
MAX_DOI_XMED = 6.0
MIN_D_OI = 0.30
MAX_TAKER_BUY = 45.0
MAX_CURRENT_DPRICE = -0.10
MAX_PREVIOUS_30M_RETURN = -0.05
MAX_PREVIOUS_2H_RETURN = -0.15
MAX_PREVIOUS_4H_RETURN = -0.30

# Regime brake: don't open SHORT in a clear higher-timeframe bullish market.
# Both returns must meet their thresholds to classify the regime as bullish.
BULL_FILTER_ENABLED = True
BULL_12H_RETURN_MIN = 0.40
BULL_24H_RETURN_MIN = 0.80

# Exhaustion brake: avoid shorting after a climactic sell-off with abnormally
# high volume. Thresholds use only data available at signal time.
CLIMAX_FILTER_ENABLED = True
CLIMAX_MIN_VOLUME_XMED = 6.0
CLIMAX_MAX_30M_RETURN = -0.45
CLIMAX_MAX_CURRENT_DPRICE = -0.45


# Optional confirmation-quality experiments (disabled by default to preserve
# the current v6.ch baseline until each experiment is run and compared).
# A) Reject confirmation records where aggressive buying is too strong.
CONFIRMATION_MAX_TAKER_BUY_ENABLED = True
CONFIRMATION_MAX_TAKER_BUY = 60.0

# B) Require price to resume moving down before entering SHORT.
# Example: 0.02 means confirmation price must be at least 0.02% below
# the signal price. This would reject the 2026-10-26 case (+0.178%).
CONFIRMATION_REQUIRE_DOWN_MOVE_ENABLED = False
CONFIRMATION_MIN_DOWN_MOVE_PCT = 0.02


# ===============================================================
# ТРИ ДОПОЛНИТЕЛЬНЫХ ФИЛЬТРА SHORT. Проверять ПО ОДНОМУ.
# Все False = исходная v7.3 (контроль), без изменения входа/TP/SL.
# True = ОТМЕНИТЬ вход, если соответствующий фильтр сработал.
# Размер позиции НЕ уменьшается. Это именно фильтры входа.
# Для честного сравнения ставь True только у одного из трёх.
# ===============================================================

# 1. ПОДДЕРЖКА S1: запретить SHORT, когда цена подтверждения
#    внутри S1 или не дальше 0.35% выше её верхней границы.
#    Смотрим только S1 из Collector за последние 60 минут.
SUPPORT_FILTER_ENABLED = True
SUPPORT_LOOKBACK_MINUTES = 60
SUPPORT_NEAR_PCT = 0.35

# 2. УСКОРЕНИЕ TAKER BUY: запретить SHORT, когда TakerBuy
#    вырос на 7 процентных пунктов или больше за ~20 минут.
TAKER_RISE_FILTER_ENABLED = False
TAKER_LOOKBACK_MINUTES = 20
TAKER_LOOKBACK_MAX_STALENESS_MINUTES = 10
TAKER_RISE_THRESHOLD_PP = 7.0

# 3. ЦЕНА ПЕРЕД ВХОДОМ: смотрим OPEN свечи Binance 1m
#    ровно через 3 минуты после подтверждения. Если цена уже
#    упала >= 0.20%, отменяем SHORT.
#    ВАЖНО: при True разрешённые сделки тоже открываются
#    спустя 3 минуты ПО НОВОЙ ЦЕНЕ (иначе был бы look-ahead).
#    Поэтому даже неотменённые сделки могут дать другой TP/SL.
PREENTRY_FILTER_ENABLED = False
PREENTRY_DELAY_MINUTES = 3
PREENTRY_FALL_THRESHOLD_PCT = 0.20
