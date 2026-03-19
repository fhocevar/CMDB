import ipaddress
import platform
import subprocess

from app.core.config import settings
from app.schemas.asset import AssetCreate


def _ping(ip: str) -> bool:
    count_flag = "-n" if platform.system().lower() == "windows" else "-c"
    timeout_flag = "-w" if platform.system().lower() == "windows" else "-W"

    try:
        result = subprocess.run(
            ["ping", count_flag, "1", timeout_flag, "1000", ip],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def discover_by_ping() -> list[AssetCreate]:
    assets: list[AssetCreate] = []

    for network_str in settings.discovery_networks:
        network = ipaddress.ip_network(network_str, strict=False)
        for host in network.hosts():
            ip = str(host)
            if _ping(ip):
                hostname = f"host-{ip.replace('.', '-')}"
                assets.append(
                    AssetCreate(
                        hostname=hostname,
                        asset_type="NETWORK_DEVICE",
                        environment="PRD",
                        criticality="MEDIA",
                        business_service="REDE",
                        ip_address=ip,
                        operating_system="UNKNOWN",
                        cpu_cores=1,
                        memory_gb=1,
                        disk_gb=1,
                        network_mbps=100,
                        source="DISCOVERY_PING",
                    )
                )

    return assets
