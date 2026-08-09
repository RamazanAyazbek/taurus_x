import math

def calculate_metrics(current_oi: float, history: list, current_price: float,
                      init_price: float, init_oi: float) -> dict:
    """
    Вычисляет медиану, Z-Score, отклонения и дельты. Чистая математика без логов.
    """
    oi_values = [item["open_interest"] for item in history]
    if not oi_values:
        return {"deviation": 0.0, "z_score": 0.0, "is_anomaly": False, "median": current_oi, "mean": current_oi}

    n = len(oi_values)
    sorted_oi = sorted(oi_values)

    # Расчет медианы и среднего
    median = sorted_oi[n // 2] if n % 2 == 1 else (sorted_oi[(n // 2) - 1] + sorted_oi[n // 2]) / 2.0
    mean = sum(oi_values) / n

    # Расчет стандартного отклонения (sigma)
    variance = sum((x - mean) ** 2 for x in oi_values) / n
    sigma = math.sqrt(variance) if variance > 0 else 1.0

    # Вычисление Z-Score и нормализованного отклонения
    z_score = (current_oi - median) / sigma
    deviation = (current_oi - median) / median if median > 0 else 0.0
    deviation = max(-1.0, min(1.0, deviation))

    # Расчет процентных дельт
    price_pct = ((current_price - init_price) / init_price) * 100 if init_price > 0 else 0.0
    oi_pct = ((current_oi - init_oi) / init_oi) * 100 if init_oi > 0 else 0.0

    return {
        "deviation": round(deviation, 4),
        "z_score": round(z_score, 2),
        "price_pct": round(price_pct, 4),
        "oi_pct": round(oi_pct, 4),
        "is_anomaly": abs(z_score) > 2.0,
        "median": median,
        "mean": mean
    }