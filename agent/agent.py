import json
import platform
import shutil
import socket
import subprocess
import time
from datetime import datetime

import psutil
import requests


def load_config():
    with open("config.json", "r", encoding="utf-8") as file:
        return json.load(file)


def get_ip_address():
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return None


def get_inventory(config):
    vm = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    return {
        "agent_token": config["agent_token"],
        "agent_version": config["agent_version"],
        "hostname": socket.gethostname(),
        "operating_system": platform.platform(),
        "ip_address": get_ip_address(),
        "environment": config["environment"],
        "criticality": config["criticality"],
        "business_service": config["business_service"],
        "cpu_cores": psutil.cpu_count(logical=True) or 1,
        "memory_gb": round(vm.total / (1024 ** 3), 2),
        "disk_gb": round(disk.total / (1024 ** 3), 2),
        "network_mbps": config["network_mbps"],
        "asset_type": config["asset_type"],
    }


def _parse_size_to_mb(value: str) -> float:
    value = value.strip().upper().replace("IB", "B")
    if value.endswith("KB"):
        return float(value[:-2]) / 1024
    if value.endswith("MB"):
        return float(value[:-2])
    if value.endswith("GB"):
        return float(value[:-2]) * 1024
    if value.endswith("B"):
        return float(value[:-1]) / (1024 * 1024)
    return 0.0


def collect_docker_containers(config):
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{ json . }}"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return []

        containers = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)

            mem_perc = str(row.get("MemPerc", "0")).replace("%", "").strip() or "0"
            cpu_perc = str(row.get("CPUPerc", "0")).replace("%", "").strip() or "0"

            net_io = row.get("NetIO", "0B / 0B")
            parts = [item.strip() for item in net_io.split("/")]
            total_mb = 0.0
            for item in parts:
                total_mb += _parse_size_to_mb(item)

            network_percent = 0.0
            if config["network_mbps"] > 0:
                network_percent = min(round((total_mb * 8 / config["network_mbps"]) * 100, 2), 100.0)

            containers.append(
                {
                    "container_id": row.get("ID", ""),
                    "container_name": row.get("Name", ""),
                    "cpu_percent": round(float(cpu_perc), 2),
                    "memory_percent": round(float(mem_perc), 2),
                    "network_percent": network_percent,
                }
            )
        return containers
    except Exception:
        return []


def get_metrics(config):
    net1 = psutil.net_io_counters()
    time.sleep(1)
    net2 = psutil.net_io_counters()

    bytes_sent_per_sec = net2.bytes_sent - net1.bytes_sent
    bytes_recv_per_sec = net2.bytes_recv - net1.bytes_recv
    total_bps = (bytes_sent_per_sec + bytes_recv_per_sec) * 8
    total_mbps = total_bps / 1_000_000
    network_percent = min(round((total_mbps / config["network_mbps"]) * 100, 2), 100.0) if config["network_mbps"] > 0 else 0.0

    disk = shutil.disk_usage("/")

    return {
        "agent_token": config["agent_token"],
        "collected_at": datetime.utcnow().isoformat(),
        "metrics": [
            {"metric_type": "cpu_percent", "metric_value": round(psutil.cpu_percent(interval=1), 2), "metric_unit": "percent"},
            {"metric_type": "memory_percent", "metric_value": round(psutil.virtual_memory().percent, 2), "metric_unit": "percent"},
            {"metric_type": "disk_percent", "metric_value": round((disk.used / disk.total) * 100, 2), "metric_unit": "percent"},
            {"metric_type": "network_percent", "metric_value": network_percent, "metric_unit": "percent"},
        ],
        "docker_containers": collect_docker_containers(config),
    }


def register_agent(config):
    payload = get_inventory(config)
    response = requests.post(f"{config['api_base_url']}/agents/register", json=payload, timeout=20)
    print("REGISTER:", response.status_code, response.text)


def send_heartbeat(config):
    payload = {
        "agent_token": config["agent_token"],
        "hostname": socket.gethostname(),
        "ip_address": get_ip_address(),
        "collected_at": datetime.utcnow().isoformat(),
    }
    response = requests.post(f"{config['api_base_url']}/agents/heartbeat", json=payload, timeout=20)
    print("HEARTBEAT:", response.status_code, response.text)


def send_metrics(config):
    payload = get_metrics(config)
    response = requests.post(f"{config['api_base_url']}/agents/metrics", json=payload, timeout=30)
    print("METRICS:", response.status_code, response.text)


def main():
    config = load_config()
    register_agent(config)

    while True:
        try:
            send_heartbeat(config)
            send_metrics(config)
        except Exception as exc:
            print("ERROR:", exc)

        time.sleep(config["interval_seconds"])


if __name__ == "__main__":
    main()
