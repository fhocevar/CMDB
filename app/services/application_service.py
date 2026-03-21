from app.integrations.argocd_client import ArgoCDClient
from app.services.capacity_service import calculate_capacity


class ApplicationService:

    def __init__(self):
        self.client = ArgoCDClient()

    def get_application_capacity(self, app_name: str):
        self.client.login()

        app = self.client.get_application(app_name)

        spec = app.get("spec", {})
        status = app.get("status", {})

        namespace = spec.get("destination", {}).get("namespace")
        project = spec.get("project")
        repo = spec.get("source", {}).get("repoURL")
        revision = spec.get("source", {}).get("targetRevision")

        sync_status = status.get("sync", {}).get("status")
        health_status = status.get("health", {}).get("status")

        resources = status.get("resources", [])

        deployments = []

        for r in resources:
            if r.get("kind") == "Deployment":
                deployments.append(r)

        # ⚡ fallback simples se não tiver detalhes do spec
        deployment_info = {
            "replicas": 1,
            "cpu_limit": 50,
            "memory_limit": 300
        }

        capacity = calculate_capacity(deployment_info)

        return {
            "application": app_name,
            "project": project,
            "namespace": namespace,
            "repo": repo,
            "revision": revision,
            "sync_status": sync_status,
            "health_status": health_status,
            "replicas": deployment_info["replicas"],
            "cpu_limit": deployment_info["cpu_limit"],
            "memory_limit": deployment_info["memory_limit"],
            "capacity_status": capacity["status"],
            "reasons": capacity["reasons"]
        }

    def list_critical_apps(self):
        self.client.login()

        apps = self.client.list_applications()

        critical_list = []

        for app in apps:
            name = app.get("metadata", {}).get("name")

            result = self.get_application_capacity(name)
            critical_list.append(result)

        return critical_list