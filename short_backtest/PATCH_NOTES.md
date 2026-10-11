# Taurus V5.8 SHORT research patch (changed files only)

Патч предназначен для текущего V5.8 SHORT research, в котором уже есть независимые `short_config.py`, `short_signal_logic.py`, `backtester.py`, `research_short_hypotheses.py`, `log_parser.py` и остальной проект.

## Что изменено
- `short_config.py` — параметры строгого R1; независимые переключатели для `PUMP_THEN_REVERSAL` и `OI_UNWIND_DOWNTURN`.
- `short_signal_logic.py` — исправлена проверка максимума около R1: теперь есть верхний предел превышения границы зоны и ограничение позднего входа; добавлены отключённые гипотезы pump/reversal и OI unwind.
- `backtester.py` — новые признаки 60-минутной доходности и отклонения максимума R1 записываются в CSV.
- `research_short_hypotheses.py` — добавлен OI-unwind в log-only directional scan.
- `research_short_precursors.py` — новый event-study анализатор, с компактной консольной сводкой и подробными CSV.
- `tests/` — регрессионные и pipeline-тесты.

## Порядок локальной проверки
1. Распакуй ZIP поверх текущей папки проекта, сохраняя структуру каталогов.
2. Перед каждым OHLC-бэктестом в `config.py` измени `OUTPUT_CSV` на новое имя — это не даст затереть предыдущий результат.
3. Тест A (исправленный R1): `ENABLE_SHORT_R1_CONFIRMED_REJECTION = True`, все остальные `ENABLE_SHORT_* = False`.
4. Тест B (pump reversal): отключи R1, включи только `ENABLE_SHORT_PUMP_REVERSAL = True`.
5. Тест C (OI unwind): отключи остальные гипотезы, включи только `ENABLE_SHORT_OI_UNWIND_DOWNTURN = True`. Это экспериментальная гипотеза, не подтверждённая статистически.

Команды:
```powershell
py .\research_short_hypotheses.py
py .\research_short_precursors.py
py .\main.py
```

`research_short_hypotheses.py` и `research_short_precursors.py` измеряют движение записанной цены после сигнала. Они не проверяют внутриминутную очередность TP/SL. Для торговой оценки запускай `main.py` с Binance Futures 1m OHLC.

Проверки в тестовой копии: `python -m compileall -q .` и `python -m unittest discover -s tests -v` — **15 тестов OK**. Полный OHLC-бэктест новой логики в среде разработки не выполнялся; его нужно выполнить локально.
