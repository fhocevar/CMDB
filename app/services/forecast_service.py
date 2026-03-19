from sqlalchemy.orm import Session

from app.models.metric import Metric


def forecast_metric_30d(db: Session, asset_id: int, metric_type: str) -> float | None:
    rows = (
        db.query(Metric)
        .filter(Metric.asset_id == asset_id)
        .filter(Metric.metric_type == metric_type)
        .order_by(Metric.collected_at.asc())
        .limit(100)
        .all()
    )

    if len(rows) < 2:
        return None

    values = [float(row.metric_value) for row in rows]
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    avg_growth = sum(deltas) / len(deltas)

    projected = values[-1] + (avg_growth * 30)
    return round(projected, 2)
