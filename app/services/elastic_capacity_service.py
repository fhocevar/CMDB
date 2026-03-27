from sqlalchemy.orm import Session

from app.integrations.elastic_apm_client import ElasticApmClient


def collect_from_elastic_apm(db: Session) -> dict:
    client = ElasticApmClient()

    try:
        data = client.get_services()
    except Exception as exc:
        return {
            "status": "ERROR",
            "integration": "ELASTIC_APM",
            "message": str(exc),
        }

    return {
        "status": "OK",
        "integration": "ELASTIC_APM",
        "raw_preview": data,
    }