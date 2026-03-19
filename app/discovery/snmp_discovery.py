from app.schemas.asset import AssetCreate


def discover_by_snmp(ip_addresses: list[str]) -> list[AssetCreate]:
    assets: list[AssetCreate] = []

    for ip in ip_addresses:
        assets.append(
            AssetCreate(
                hostname=f"snmp-{ip.replace('.', '-')}",
                asset_type="NETWORK_DEVICE",
                environment="PRD",
                criticality="ALTA",
                business_service="REDE",
                ip_address=ip,
                operating_system="SNMP_DEVICE",
                cpu_cores=1,
                memory_gb=1,
                disk_gb=1,
                network_mbps=1000,
                source="DISCOVERY_SNMP",
            )
        )

    return assets
