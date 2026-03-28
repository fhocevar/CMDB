import json
from typing import Any

import winrm

from app.core.config import settings


class WinRMClient:
    def __init__(self):
        self.enabled = settings.WINRM_ENABLED
        self.username = settings.WINRM_USERNAME
        self.password = settings.WINRM_PASSWORD
        self.transport = settings.WINRM_TRANSPORT
        self.port = settings.WINRM_PORT
        self.use_ssl = settings.WINRM_USE_SSL
        self.verify_tls = settings.WINRM_VERIFY_TLS
        self.operation_timeout_sec = settings.WINRM_OPERATION_TIMEOUT_SEC
        self.read_timeout_sec = settings.WINRM_READ_TIMEOUT_SEC

    def _build_endpoint(self, host: str) -> str:
        scheme = "https" if self.use_ssl else "http"
        return f"{scheme}://{host}:{self.port}/wsman"

    def get_windows_system_metrics(self, host: str) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("WINRM está desabilitado.")

        if not self.username or not self.password:
            raise RuntimeError("Credenciais WinRM não configuradas.")

        endpoint = self._build_endpoint(host)

        session = winrm.Session(
            target=endpoint,
            auth=(self.username, self.password),
            transport=self.transport,
            server_cert_validation="validate" if self.verify_tls else "ignore",
            operation_timeout_sec=self.operation_timeout_sec,
            read_timeout_sec=self.read_timeout_sec,
        )

        ps_script = r"""
$cpu = Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average
$os = Get-CimInstance Win32_OperatingSystem
$disks = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3"

$totalMemKB = [double]$os.TotalVisibleMemorySize
$freeMemKB = [double]$os.FreePhysicalMemory
$usedMemKB = $totalMemKB - $freeMemKB

$totalDiskBytes = ($disks | Measure-Object -Property Size -Sum).Sum
$freeDiskBytes = ($disks | Measure-Object -Property FreeSpace -Sum).Sum
$usedDiskBytes = $totalDiskBytes - $freeDiskBytes

$result = @{
    cpu_load_percent   = [math]::Round(($cpu.Average), 2)
    memory_total_mb    = [math]::Round(($totalMemKB / 1024), 2)
    memory_free_mb     = [math]::Round(($freeMemKB / 1024), 2)
    memory_used_mb     = [math]::Round(($usedMemKB / 1024), 2)
    memory_used_percent = if ($totalMemKB -gt 0) { [math]::Round((($usedMemKB / $totalMemKB) * 100), 2) } else { 0 }
    disk_total_gb      = if ($totalDiskBytes -gt 0) { [math]::Round(($totalDiskBytes / 1GB), 2) } else { 0 }
    disk_free_gb       = if ($freeDiskBytes -gt 0) { [math]::Round(($freeDiskBytes / 1GB), 2) } else { 0 }
    disk_used_gb       = if ($usedDiskBytes -gt 0) { [math]::Round(($usedDiskBytes / 1GB), 2) } else { 0 }
    disk_used_percent  = if ($totalDiskBytes -gt 0) { [math]::Round((($usedDiskBytes / $totalDiskBytes) * 100), 2) } else { 0 }
    os_name            = $os.Caption
} | ConvertTo-Json -Compress

Write-Output $result
"""

        result = session.run_ps(ps_script)

        if result.status_code != 0:
            stderr = (result.std_err or b"").decode("utf-8", errors="ignore").strip()
            stdout = (result.std_out or b"").decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"Falha WinRM em {host}: {stderr or stdout or 'sem detalhe'}")

        output = (result.std_out or b"").decode("utf-8", errors="ignore").strip()
        if not output:
            raise RuntimeError(f"WinRM não retornou saída para {host}.")

        return json.loads(output)