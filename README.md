# ITIL Capacity Management API V2.2

Projeto pronto para abrir no VS Code com:

- FastAPI
- PostgreSQL
- Discovery básico
- Agent para hosts Windows/Linux
- Coleta de containers Docker
- Integrações com Prometheus, Kubernetes, Argo CD, Zabbix e VMware
- Dashboard e exportação CSV

## Como rodar

### Opção 1: Docker

```bash
docker compose up --build
```

### Opção 2: Local

```bash
python -m venv .venv
source .venv/Scripts/activate  # Git Bash no Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Credenciais iniciais

- usuário: `admin`
- senha: `admin123`

## Estrutura principal

- `app/main.py`
- `app/api/routes/`
- `app/core/`
- `app/models/`
- `app/services/`
- `app/integrations/`
- `agent/agent.py`
- `.env`
- `docker-compose.yml`

## Endpoints principais

### Saúde
- `GET /`

### Autenticação
- `POST /auth/login`

### Ativos
- `POST /assets/`
- `GET /assets/`

### Métricas
- `POST /metrics/`

### Thresholds
- `POST /thresholds/`
- `GET /thresholds/`

### Dashboard
- `GET /dashboard/capacity?hours=24`

### Discovery
- `POST /discovery/run`

### Agent
- `POST /agents/register`
- `POST /agents/heartbeat`
- `POST /agents/metrics`

### Integrações
- `POST /integrations/prometheus/run`
- `POST /integrations/kubernetes/run`
- `POST /integrations/argocd/run`
- `POST /integrations/zabbix/run`
- `POST /integrations/vmware/run`

### Exportação
- `GET /exports/capacity.csv?hours=24`

## Observações

- As integrações de Zabbix, VMware e parte do discovery SNMP estão como base pronta para adaptação ao ambiente.
- O endpoint Kubernetes espera acesso ao Metrics API.
- O endpoint Argo CD consome o endpoint de métricas Prometheus do Argo CD.
- O agent coleta host + Docker local no mesmo equipamento.
