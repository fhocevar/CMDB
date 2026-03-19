from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.metric import Metric
from app.models.metric_baseline import MetricBaseline
from app.schemas.metric import MetricCreate


def ingest_metric(db: Session, payload: MetricCreate) -> Metric:
    metric = Metric(**payload.model_dump())
    db.add(metric)
    db.commit()
    db.refresh(metric)
    return metric


def update_baseline(db: Session, asset_id: int, metric_type: str, window_days: int = 7) -> None:
    since = datetime.utcnow() - timedelta(days=window_days)

    rows = (
        db.query(Metric)
        .filter(Metric.asset_id == asset_id)
        .filter(Metric.metric_type == metric_type)
        .filter(Metric.collected_at >= since)
        .all()
    )

    if not rows:
        return

    values = [float(item.metric_value) for item in rows]
    baseline_avg = sum(values) / len(values)
    baseline_peak = max(values)

    baseline = (
        db.query(MetricBaseline)
        .filter(MetricBaseline.asset_id == asset_id)
        .filter(MetricBaseline.metric_type == metric_type)
        .first()
    )

    if baseline:
        baseline.baseline_avg = baseline_avg
        baseline.baseline_peak = baseline_peak
        baseline.reference_window_days = window_days
    else:
        baseline = MetricBaseline(
            asset_id=asset_id,
            metric_type=metric_type,
            baseline_avg=baseline_avg,
            baseline_peak=baseline_peak,
            reference_window_days=window_days,
        )
        db.add(baseline)

    db.commit()
