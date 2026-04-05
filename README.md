# Cadê Você (cadevoce)

Sistema de rastreamento de notebooks corporativos: o agente tenta **GPS (Windows Location / Wi‑Fi)** e, se a precisão for ruim ou falhar, cai para **IP** com **[ip-api.com](http://ip-api.com)**. Com GPS, o backend usa **Azure Maps** (reverse geocode) para obter estado/cidade. Valida o **estado permitido**, grava histórico, aplica **limiar de tempo** antes do primeiro alerta no **Teams** e serve o **dashboard** (Leaflet) no FastAPI.

## Requisitos

- Python **3.11+**
- (Opcional) Incoming Webhook do Teams para alertas

## Instalação local

Na pasta raiz do projeto (onde estão `backend/`, `dashboard/` e `requirements.txt`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edite o `.env`:

| Variável | Descrição |
|----------|-----------|
| `TEAMS_WEBHOOK_URL` | URL do webhook do Teams (pode ficar vazio para desativar alertas) |
| `DATABASE_URL` | Padrão dev: `sqlite+aiosqlite:///./cadevoce.db` |
| `API_SECRET_KEY` | Chave compartilhada com o agente (header `X-API-Key`) |
| `AZURE_MAPS_KEY` | Chave Azure Maps (obrigatória se usar check-ins `source: gps`) |
| `VIOLATION_THRESHOLD_MINUTES` | Minutos fora do estado antes do primeiro alerta (padrão: 20) |

Subir a API e o dashboard:

```powershell
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

- API: `http://127.0.0.1:8000/docs` (Swagger)
- Dashboard: `http://127.0.0.1:8000/`

## Checklist de go-live

Use nesta ordem em homologação e, depois, em produção.

1. **Ambiente e `.env`**
   - Copiar `.env.example` → `.env` (se ainda não existir).
   - Definir `API_SECRET_KEY` (valor forte; o mesmo será usado pelo agente).
   - Se for usar GPS no agente: preencher `AZURE_MAPS_KEY`.
   - Ajustar `VIOLATION_THRESHOLD_MINUTES` se quiser outro limiar (padrão 20).
   - Opcional: `TEAMS_WEBHOOK_URL` para alertas no canal.
   - Opcional: `DATABASE_URL` apontando para o banco de produção quando migrar.

2. **Dependências e API**
   - `pip install -r requirements.txt` (com venv ativado).
   - Subir: `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000` (em produção use host/porta/reverse proxy conforme sua infra).
   - Abrir `http://127.0.0.1:8000/docs` e confirmar que a API responde.

3. **Cadastro de dispositivos**
   - Para cada notebook/usuário: `POST /devices` com `hostname`, `username`, `estado_permitido` (sigla BR, ex. `SP`, `DF`).
   - Conferir no PC: `$env:COMPUTERNAME` e `$env:USERNAME` batem com o cadastro.

4. **Teste de check-in (sem agente)**
   - `POST /checkin` com `X-API-Key` igual a `API_SECRET_KEY`.
   - Teste legado (só IP): corpo com `hostname`, `username`, `ip`, `timestamp`.
   - Opcional GPS: corpo com `source: gps`, `latitude`, `longitude`, `accuracy` (exige `AZURE_MAPS_KEY` no servidor).
   - Esperado: `200` e `{"ok": true}`; erros `401` (chave), `404` (device não cadastrado), `502` (geo/Azure).

5. **Dashboard**
   - Abrir `http://127.0.0.1:8000/` (mesma origem que a API).
   - Confirmar mapa, tabela, badges e último check-in após o passo 4.

6. **Microsoft Teams**
   - Criar Incoming Webhook no canal desejado e colar a URL em `TEAMS_WEBHOOK_URL`.
   - Reiniciar a API após alterar o `.env`.
   - Simular violação **contínua**: estado detectado diferente do permitido por mais de `VIOLATION_THRESHOLD_MINUTES` (vários check-ins ou tempo real); esperado **um** card no Teams por janela de violação (enquanto `alert_sent` for falso até disparar).

7. **Agente nos notebooks**
   - Definir `CADEVOCE_API_URL` (URL pública ou interna da API) e `CADEVOCE_API_KEY` (= `API_SECRET_KEY`).
   - Executar manualmente `agent.ps1` uma vez; ler `%TEMP%\cadevoce.log`.
   - No Windows: garantir **localização** ligada se quiser priorizar GPS.
   - Criar **Tarefa Agendada** (ex.: a cada 10 min) ou distribuir via **Intune** (ver seção abaixo).

8. **Antes de produção**
   - HTTPS na API, firewall e rota até os notebooks.
   - Backup do banco (`cadevoce.db` ou Azure SQL).
   - Revisar rotação de `API_SECRET_KEY` e armazenamento da chave (não commitar `.env`).

## Cadastrar um dispositivo de teste

Todo check-in exige um registro prévio em `devices` (hostname + usuário + estado permitido):

```powershell
curl -X POST http://127.0.0.1:8000/devices `
  -H "Content-Type: application/json" `
  -d "{\"hostname\": \"NOTEBOOK-TESTE\", \"username\": \"usuario\", \"estado_permitido\": \"SP\"}"
```

Ajuste `hostname` e `username` para bater com o PC de teste (`$env:COMPUTERNAME` e `$env:USERNAME` no PowerShell).

## Simular um check-in com curl

Use a mesma chave definida em `API_SECRET_KEY` no `.env`:

```powershell
curl -X POST http://127.0.0.1:8000/checkin `
  -H "Content-Type: application/json" `
  -H "X-API-Key: SUA_CHAVE_AQUI" `
  -d "{\"hostname\": \"NOTEBOOK-TESTE\", \"username\": \"usuario\", \"ip\": \"8.8.8.8\", \"timestamp\": \"2026-04-02T12:00:00Z\"}"
```

Respostas comuns:

- `404` — dispositivo não cadastrado em `POST /devices`
- `401` — `X-API-Key` ausente ou incorreta

## Endpoints principais

| Método | Caminho | Descrição |
|--------|---------|-----------|
| `POST` | `/checkin` | Heartbeat do agente (requer `X-API-Key`) |
| `POST` | `/devices` | Cria ou atualiza dispositivo |
| `GET` | `/devices` | Último check-in por dispositivo (dashboard) |
| `GET` | `/violations` | Histórico de violações (`username`, `date_from`, `date_to` opcionais) |

## VPN / proxy / hosting (ip-api.com)

Se o ip-api indicar `proxy` ou `hosting`, o check-in é gravado com `vpn_detected=true`, o mapa usa marcador com indicação visual e a tabela mostra ícone de VPN. **Não bloqueia** a validação de estado.

## Payload do check-in (`POST /checkin`)

- **Legado (só IP):** `hostname`, `username`, `ip`, `timestamp` — equivale a `source: ip`.
- **Novo:** `source` = `gps` | `ip`; com `gps` envie `latitude`, `longitude` e opcionalmente `accuracy` e `ip`; com `ip` envie `ip`.

Alertas no Teams só após o dispositivo permanecer **fora do estado permitido** por `VIOLATION_THRESHOLD_MINUTES` (janela em `violation_windows`).

## Agente PowerShell (`agent/agent.ps1`)

### Compilar o GeoHelper (GPS no Windows)

Na pasta `agent/GeoHelper` (com [.NET 8 SDK](https://dotnet.microsoft.com/download) instalado):

```powershell
cd agent\GeoHelper
dotnet publish -c Release -r win-x64 --self-contained true -o ./publish
```

Isso gera `agent/GeoHelper/publish/GeoHelper.exe`. O `agent.ps1` usa esse caminho por padrão; para outro local, defina `CADEVOCE_GEOHELPER_EXE`.

1. Copie `agent.ps1` e a pasta `GeoHelper\publish\` (com `GeoHelper.exe`) para os notebooks (ou publique via Intune).
2. Defina variáveis de ambiente **ou** edite o script:
   - `CADEVOCE_API_URL` — URL base da API (ex.: `https://api.suaempresa.com`)
   - `CADEVOCE_API_KEY` — mesmo valor de `API_SECRET_KEY`
   - `CADEVOCE_GEOHELPER_EXE` — (opcional) caminho completo do `GeoHelper.exe`
3. Teste manualmente:

```powershell
$env:CADEVOCE_API_URL = 'http://127.0.0.1:8000'
$env:CADEVOCE_API_KEY = 'SUA_CHAVE'
powershell -ExecutionPolicy Bypass -File .\agent\agent.ps1
```

4. Log local: `%TEMP%\cadevoce.log`

### Distribuição via Microsoft Intune

1. **Conteúdo**: faça upload do `agent.ps1` (ou de um `.intunewin` que apenas extraia e execute o script).
2. **Política de configuração** ou **Scripts do PowerShell** (conforme o que a organização usa):
   - Comando sugerido: `powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\ProgramData\BravoTI\cadevoce\agent.ps1"`
3. **Agendamento**: use **Task Scheduler** em cada máquina (ou um segundo script/Intune que crie a tarefa):
   - Disparo: a cada **10 minutos**
   - Usuário: **SYSTEM** ou conta com rede; garanta que o IP público seja obtível
   - “Executar com privilégios mais altos” se necessário na sua política
4. **Segredo**: prefira injetar `CADEVOCE_API_KEY` via Intune (variável de ambiente de sistema ou arquivo protegido), em vez de texto puro no script em repositórios públicos.

## Banco de dados (produção / Azure SQL)

Em desenvolvimento o projeto usa **SQLite** assíncrono (`aiosqlite`). Para **Azure SQL**, altere `DATABASE_URL` para uma URL assíncrona compatível (ex.: driver `aioodbc` + ODBC Azure) e instale o driver correspondente no `requirements.txt`. O modelo SQLAlchemy permanece o mesmo; ajuste apenas a string de conexão e dependências no ambiente de deploy.

## Estrutura

```
cadevoce/
├── agent/agent.ps1
├── agent/GeoHelper/   (projeto C# → publish/GeoHelper.exe)
├── backend/
├── dashboard/
├── .env.example
├── requirements.txt
└── README.md
```

## Licença de uso

Uso interno Bravo TI — ajuste conforme a política da empresa.
