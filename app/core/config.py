from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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

    DISCOVERY_PING_ENABLED: bool = True
    DISCOVERY_SSH_ENABLED: bool = False
    DISCOVERY_SNMP_ENABLED: bool = False

    DISCOVERY_NETWORKS: str = ""
    DISCOVERY_SSH_USER: str = ""
    DISCOVERY_SSH_PASSWORD: str = ""
    DISCOVERY_SNMP_COMMUNITY: str = "public"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def discovery_networks(self) -> list[str]:
        return [item.strip() for item in self.DISCOVERY_NETWORKS.split(",") if item.strip()]


settings = Settings()
