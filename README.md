
# ITIL Capacity Management API V2.2

Plataforma de **CMDB + Capacity + Observabilidade de Deploy** baseada em:

- FastAPI (backend)
- PostgreSQL (persistência)
- Argo CD (fonte de deploy)
- Streamlit (dashboard opcional)
- Integrações com Prometheus, Kubernetes, Zabbix, VMware

---

# 🚀 Principais funcionalidades

## 🔹 CMDB & Capacity
- Cadastro e gestão de ativos
- Coleta de métricas
- Thresholds por tipo de ativo
- Cálculo de capacity

## 🔹 Argo CD (NOVO 🔥)
- Inventário completo de aplicações
- Estado de deploy (sync / health)
- Detecção de drift (OutOfSync)
- Detecção de falhas (Degraded / Missing)
- Histórico de execuções
- Topologia de recursos Kubernetes (via Argo)
- Extração de imagens e versões

## 🔹 Capacity Score (NOVO 🔥)
Score de 0 a 100 baseado em:
- Health status
- Sync status
- Falhas de operação
- Recursos degradados
- Conditions
- Governança (auto-sync, self-heal)

Classificação:
- `SAUDAVEL`
- `ATENCAO`
- `CRITICO`
- `SATURADO`

## 🔹 Dashboard
- Dashboard HTML estilo Grafana (embutido na API)
- Dashboard Streamlit (opcional, mais avançado)
- Histórico de capacity
- Ranking de aplicações críticas

---

# 🏗️ Arquitetura

```

Argo CD → FastAPI → PostgreSQL → Dashboard (HTML / Streamlit)

````

---

# ▶️ Como rodar

## 🔹 Opção 1: Docker

```bash
docker compose up --build
````

Acessos:

* API: [http://localhost:8000](http://localhost:8000)
* Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)
* Dashboard HTML: [http://localhost:8000/applications/capacity/dashboard/html](http://localhost:8000/applications/capacity/dashboard/html)

---

## 🔹 Opção 2: Local

```bash
python -m venv .venv
source .venv/Scripts/activate  # Git Bash (Windows)

pip install -r requirements.txt
uvicorn app.main:app --reload
```

---

# 🔐 Credenciais iniciais

* usuário: `admin`
* senha: `admin123`

---

# 📊 Dashboard

## 🔹 HTML (embutido)

```
GET /applications/capacity/dashboard/html
```

## 🔹 JSON

```
GET /applications/capacity/dashboard
```

## 🔹 Histórico

```
GET /applications/capacity/history?days=30
```

---

# 🧠 Capacity (Argo CD)

## 🔹 Coletar snapshot (persiste no banco)

```
POST /applications/capacity/collect
```

## 🔹 Listar aplicações (live)

```
GET /applications/capacity
```

## 🔹 Detalhar aplicação

```
GET /applications/capacity/{app_name}
```

---

# 📈 Streamlit (opcional 🔥)

## Instalar

```bash
pip install -r requirements-streamlit.txt
```

## Rodar

```bash
streamlit run streamlit_app.py
```

Acesso:

```
http://localhost:8501
```

## Docker (opcional)

Adicionar no `docker-compose.yml`:

```yaml
streamlit:
  image: python:3.12-slim
  working_dir: /app
  volumes:
    - .:/app
  command: >
    sh -c "pip install -r requirements-streamlit.txt &&
           streamlit run streamlit_app.py --server.port 8501 --server.address 0.0.0.0"
  environment:
    API_BASE_URL: http://api:8000
  ports:
    - "8501:8501"
```

---

# 📦 Estrutura principal

```
app/
  main.py
  api/routes/
  core/
  models/
    app_capacity_snapshot.py  # NOVO
  services/
    application_service.py    # NOVO (capacity + score)
  integrations/
```

---

# 📊 Banco de dados

Tabela nova:

### `app_capacity_snapshots`

Armazena:

* aplicação
* projeto / namespace
* status (sync / health)
* operação (phase, duration, erro)
* recursos (degraded, missing, etc)
* imagens
* capacity_score
* capacity_status
* reasons
* run_id (execução)

---

# 🔌 Integrações

### Prometheus

```
POST /integrations/prometheus/run
```

### Kubernetes

```
POST /integrations/kubernetes/run
```

### Argo CD

```
POST /integrations/argocd/run
```

### Zabbix

```
POST /integrations/zabbix/run
```

### VMware

```
POST /integrations/vmware/run
```

---

# 🤖 Agent

* `POST /agents/register`
* `POST /agents/heartbeat`
* `POST /agents/metrics`

---

# 🔎 Discovery

```
POST /discovery/run
```

---

# 📤 Exportação

```
GET /exports/capacity.csv?hours=24
```

---

# ⚠️ Observações importantes

* Argo CD não fornece métricas reais de CPU/memória (somente estado de deploy)
* Capacity Score é baseado em risco operacional (não consumo real)
* Para métricas reais, integrar com:

  * Kubernetes API
  * Prometheus

---

# 🚀 Próximos passos recomendados

* Agendamento automático de coleta (scheduler)
* Alertas (Teams / Email)
* Filtros avançados no Streamlit
* Comparação entre execuções (diff)
* Integração com Prometheus para capacity real