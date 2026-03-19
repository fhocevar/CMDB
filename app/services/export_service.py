import io

import pandas as pd

from app.schemas.dashboard import DashboardSummary


def dashboard_to_csv_bytes(dashboard: DashboardSummary) -> bytes:
    df = pd.DataFrame([item.model_dump() for item in dashboard.items])
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")
