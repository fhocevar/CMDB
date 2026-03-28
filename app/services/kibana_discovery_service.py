from sqlalchemy.orm import Session

from app.integrations.kibana_client import KibanaClient


def discover_kibana(db: Session) -> dict:
    try:
        client = KibanaClient()
        status = client.get_status()
        data_views = client.list_data_views()
    except Exception as exc:
        return {
            "status": "ERROR",
            "integration": "KIBANA",
            "message": str(exc),
        }

    views = data_views.get("data_view", []) or data_views.get("data_views", []) or []

    simplified_views = []
    for item in views:
        simplified_views.append(
            {
                "id": item.get("id"),
                "name": item.get("name") or item.get("title"),
                "title": item.get("title"),
            }
        )

    return {
        "status": "OK",
        "integration": "KIBANA",
        "kibana_name": status.get("name"),
        "kibana_version": (status.get("version") or {}).get("number"),
        "overall_status": ((status.get("status") or {}).get("overall") or {}).get("level"),
        "data_views_total": len(simplified_views),
        "data_views": simplified_views,
        "limitations": [
            "Esta instância do Kibana permite inventário e status, mas não expõe um caminho utilizável para consultas de métricas do Elasticsearch pela aplicação.",
            "Sem acesso ao Elasticsearch ou a um proxy equivalente, métricas de capacity como CPU, memória, disco e APM não podem ser calculadas por este endpoint."
        ]
    }