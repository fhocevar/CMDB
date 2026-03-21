from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.metric import Metric
from app.models.metric_baseline import MetricBaseline
from app.models.threshold_policy import ThresholdPolicy
from app.schemas.dashboard import CapacityStatusItem, DashboardSummary
from app.services.forecast_service import forecast_metric_30d


SUPPORTED_METRICS = [
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "network_percent",
    "container_cpu_percent",
    "container_memory_percent",
    "container_network_percent",
    "argocd_sync_state",
    "argocd_health_state",
]


def calculate_capacity(deployment: dict) -> dict:
    replicas = deployment.get("replicas", 1)
    cpu = deployment.get("cpu_limit", 0)
    memory = deployment.get("memory_limit", 0)

    reasons = []
    status = "SAUDAVEL"

    if replicas == 1:
        status = "CRITICO"
        reasons.append("Sem alta disponibilidade (replicas=1)")
    elif replicas == 2 and status != "CRITICO":
        status = "ATENCAO"
        reasons.append("Baixa redundância (replicas=2)")

    if cpu < 50:
        status = "CRITICO"
        reasons.append("CPU muito baixo")
    elif cpu < 100 and status != "CRITICO":
        status = "ATENCAO"
        reasons.append("CPU abaixo do ideal")

    if memory < 128:
        status = "CRITICO"
        reasons.append("Memória muito baixa")
    elif memory < 256 and status != "CRITICO":
        status = "ATENCAO"
        reasons.append("Memória abaixo do ideal")

    return {
        "status": status,
        "reasons": reasons,
    }


def _derive_status(utilization_percent: float, warning: float, critical: float, saturation: float) -> str:
    if utilization_percent >= saturation:
        return "SATURADO"
    if utilization_percent >= critical:
        return "CRITICO"
    if utilization_percent >= warning:
        return "ATENCAO"
    return "SAUDAVEL"


def _derive_trend(latest_value: float, avg_value: float, baseline_avg: float | None) -> str:
    if baseline_avg is not None and latest_value > baseline_avg * 1.15:
        return "CRESCENTE"
    if latest_value < avg_value * 0.8:
        return "ESTAVEL_BAIXO"
    return "ESTAVEL"


def build_dashboard(db: Session, hours: int = 24) -> DashboardSummary:
    since = datetime.utcnow() - timedelta(hours=hours)

    assets = db.query(Asset).filter(Asset.is_active.is_(True)).all()
    policies = db.query(ThresholdPolicy).filter(ThresholdPolicy.is_active.is_(True)).all()
    baselines = db.query(MetricBaseline).all()

    policy_map = {(p.asset_type, p.metric_type): p for p in policies}
    baseline_map = {(b.asset_id, b.metric_type): b for b in baselines}

    metrics = (
        db.query(Metric)
        .filter(Metric.collected_at >= since)
        .order_by(Metric.asset_id, Metric.metric_type, Metric.collected_at.desc())
        .all()
    )

    grouped = defaultdict(list)
    for metric in metrics:
        grouped[(metric.asset_id, metric.metric_type)].append(metric)

    items: list[CapacityStatusItem] = []

    for asset in assets:
        for metric_type in SUPPORTED_METRICS:
            series = grouped.get((asset.id, metric_type), [])
            if not series:
                continue

            latest = series[0]
            values = [float(x.metric_value) for x in series]
            latest_value = float(latest.metric_value)
            avg_value = round(sum(values) / len(values), 2)
            peak_value = round(max(values), 2)

            policy = policy_map.get((asset.asset_type, metric_type)) or policy_map.get(("DEFAULT", metric_type))
            if not policy:
                policy = policy_map.get((asset.asset_type, "cpu_percent")) or policy_map.get(("DEFAULT", "cpu_percent"))
            if not policy:
                continue

            baseline = baseline_map.get((asset.id, metric_type))
            baseline_avg = round(float(baseline.baseline_avg), 2) if baseline else None
            forecast_30d = forecast_metric_30d(db, asset.id, metric_type)

            status = _derive_status(
                latest_value,
                float(policy.warning_percent),
                float(policy.critical_percent),
                float(policy.saturation_percent),
            )
            trend = _derive_trend(latest_value, avg_value, baseline_avg)

            items.append(
                CapacityStatusItem(
                    asset_id=asset.id,
                    hostname=asset.hostname,
                    asset_type=asset.asset_type,
                    environment=asset.environment,
                    criticality=asset.criticality,
                    business_service=asset.business_service,
                    metric_type=metric_type,
                    latest_value=round(latest_value, 2),
                    peak_value=peak_value,
                    avg_value=avg_value,
                    baseline_avg=baseline_avg,
                    forecast_30d=forecast_30d,
                    capacity_limit=100.0,
                    utilization_percent=round(latest_value, 2),
                    status=status,
                    trend=trend,
                    collected_at=latest.collected_at,
                )
            )

    severity_rank = {"SAUDAVEL": 1, "ATENCAO": 2, "CRITICO": 3, "SATURADO": 4}
    asset_status_map: dict[int, str] = {}

    for item in items:
        current = asset_status_map.get(item.asset_id)
        if not current or severity_rank[item.status] > severity_rank[current]:
            asset_status_map[item.asset_id] = item.status

    return DashboardSummary(
        total_assets=len(asset_status_map),
        healthy_assets=sum(1 for v in asset_status_map.values() if v == "SAUDAVEL"),
        warning_assets=sum(1 for v in asset_status_map.values() if v == "ATENCAO"),
        critical_assets=sum(1 for v in asset_status_map.values() if v == "CRITICO"),
        saturated_assets=sum(1 for v in asset_status_map.values() if v == "SATURADO"),
        items=items,
    )