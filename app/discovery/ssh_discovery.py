import paramiko

from app.core.config import settings
from app.schemas.asset import AssetCreate


def discover_by_ssh(ip_addresses: list[str]) -> list[AssetCreate]:
    assets: list[AssetCreate] = []

    for ip in ip_addresses:
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(
                hostname=ip,
                username=settings.DISCOVERY_SSH_USER,
                password=settings.DISCOVERY_SSH_PASSWORD,
                timeout=5,
            )

            _, stdout, _ = ssh.exec_command(
                "hostname && uname -s && nproc && free -g | awk '/Mem:/ {print $2}' && df -BG / | tail -1 | awk '{print $2}'"
            )
            output = stdout.read().decode().strip().splitlines()

            if len(output) >= 5:
                hostname = output[0]
                os_name = output[1]
                cpu_cores = int(output[2])
                memory_gb = float(output[3])
                disk_gb = float(str(output[4]).replace('G', ''))

                assets.append(
                    AssetCreate(
                        hostname=hostname,
                        asset_type="SERVER",
                        environment="PRD",
                        criticality="ALTA",
                        business_service="INFRAESTRUTURA",
                        ip_address=ip,
                        operating_system=os_name,
                        cpu_cores=cpu_cores,
                        memory_gb=memory_gb,
                        disk_gb=disk_gb,
                        network_mbps=1000,
                        source="DISCOVERY_SSH",
                    )
                )

            ssh.close()
        except Exception:
            continue

    return assets
