from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "ITIL Capacity Management API V2.2"
    DEBUG: bool = True

    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str

    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480

    DEFAULT_AGENT_TOKEN: str = "agent-default-token"

    PROMETHEUS_URL: str = "http://prometheus:9090"
    PROMETHEUS_ENABLED: bool = False

    KUBERNETES_ENABLED: bool = False
    KUBERNETES_API_URL: str = ""
    KUBERNETES_BEARER_TOKEN: str = ""
    KUBERNETES_VERIFY_TLS: bool = False
    KUBERNETES_CLUSTER_NAME: str = "aks-default"

    ZABBIX_ENABLED: bool = False
    ZABBIX_URL: str = ""
    ZABBIX_USER: str = ""
    ZABBIX_PASSWORD: str = ""

    VMWARE_ENABLED: bool = False
    VMWARE_HOST: str = ""
    VMWARE_USER: str = ""
    VMWARE_PASSWORD: str = ""

    ARGOCD_ENABLED: bool = False
    ARGOCD_METRICS_URL: str = ""
    ARGOCD_NAMESPACE: str = "argocd"

    ARGOCD_URL: str = ""
    ARGOCD_USERNAME: str = ""
    ARGOCD_PASSWORD: str = ""
    ARGOCD_VERIFY_TLS: bool = False

    CRITICAL_APPS: str = ""

    DISCOVERY_PING_ENABLED: bool = True
    DISCOVERY_SSH_ENABLED: bool = False
    DISCOVERY_SNMP_ENABLED: bool = False

    DISCOVERY_NETWORKS: str = ""
    DISCOVERY_SSH_USER: str = ""
    DISCOVERY_SSH_PASSWORD: str = ""
    DISCOVERY_SNMP_COMMUNITY: str = "public"

    JENKINS_ENABLED: bool = False
    JENKINS_URL: str = ""
    JENKINS_USER: str = ""
    JENKINS_PASSWORD: str = ""
    JENKINS_VERIFY_TLS: bool = False

    KIBANA_URL: str = ""
    KIBANA_USER: str = ""
    KIBANA_PASSWORD: str = ""
    KIBANA_VERIFY_TLS: bool = False

    ELASTICSEARCH_ENABLED: bool = False
    ELASTICSEARCH_URL: str = ""
    ELASTICSEARCH_USER: str = ""
    ELASTICSEARCH_PASSWORD: str = ""
    ELASTICSEARCH_VERIFY_TLS: bool = False

    WINRM_ENABLED: bool = False
    WINRM_USERNAME: str = ""
    WINRM_PASSWORD: str = ""
    WINRM_TRANSPORT: str = "ntlm"
    WINRM_PORT: int = 5985
    WINRM_USE_SSL: bool = False
    WINRM_VERIFY_TLS: bool = False
    WINRM_OPERATION_TIMEOUT_SEC: int = 30
    WINRM_READ_TIMEOUT_SEC: int = 45
    WINRM_HOSTS: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def discovery_networks(self) -> list[str]:
        return [item.strip() for item in self.DISCOVERY_NETWORKS.split(",") if item.strip()]

    @property
    def critical_apps(self) -> list[str]:
        return [item.strip() for item in self.CRITICAL_APPS.split(",") if item.strip()]


settings = Settings()