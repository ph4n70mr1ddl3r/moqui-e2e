# Headless ERP

API-first headless ERP built on [Moqui Framework](https://moqui.org) + [Mantle](https://moqui.org/mantle.html).

## Quick Start

```bash
# Clone and run — everything boots with one command
git clone https://github.com/ph4n70mr1ddl3r/headless.git
cd headless
docker compose up
```

The stack starts two containers:

| Service | Image | Port | Purpose |
|---|---|---|---|
| **postgres** | postgres:16-alpine | 5432 | Primary database |
| **app** | built from source | 8080 | Moqui headless ERP |

On first boot, tables are auto-created and seed data is loaded (~7500 records, ~30s).

## First Request

```bash
# Health check
curl http://localhost:8080/rest/s1/headless/health

# Login as admin (default: admin/admin)
curl -u admin:admin http://localhost:8080/rest/s1/headless/stats

# Create an API key
curl -u admin:admin -X POST http://localhost:8080/rest/s1/headless/apiKeys/create \
  -H "Content-Type: application/json" \
  -d '{"userId":"ADMIN_USER","name":"My App","scopes":"read,write"}'
# → {"rawKey": "hlp_...", "apiKeyId": "..."}

# Use the API key (no username/password needed)
curl -H "Authorization: Bearer hlp_..." http://localhost:8080/rest/s1/mantle/orders
```

## API Endpoints

### Headless ERP (`/rest/s1/headless/`)

| Path | Methods | Description |
|---|---|---|
| `/health` | GET | System health (load balancers) |
| `/stats` | GET | Dashboard statistics |
| `/activity` | GET | Recent activity feed |
| `/apiKeys` | GET, POST | API key management |
| `/apiKeys/{id}` | GET, DELETE | View/revoke a key |
| `/apiKeys/{id}/rotate` | POST | Rotate a key |
| `/apiKeys/validate` | POST | Validate a raw key |
| `/webhooks` | GET, POST | Webhook endpoints |
| `/webhooks/{id}` | GET, PATCH | View/update webhook |
| `/webhooks/{id}/deliveries` | GET | Delivery history |
| `/webhooks/retryFailed` | POST | Retry failed deliveries |
| `/audit` | GET | API audit trail |
| `/rateLimits` | GET, POST | Rate limit config |

### Mantle ERP (`/rest/s1/mantle/`)

| Path | Description |
|---|---|
| `/parties` | Customers, suppliers, employees |
| `/products` | Goods, materials, services |
| `/orders` | Purchase & sales orders |
| `/shipments` | Incoming & outgoing |
| `/assets` | Inventory, equipment |
| `/facilities` | Warehouses, offices |
| `/workEfforts` | Projects, tasks, production runs |

Plus full entity CRUD at `/rest/e1/` for all 878 entity definitions.

## Configuration

Override via environment variables or `-D` system properties:

| Variable | Default | Description |
|---|---|---|
| `ENTITY_DS_DB_HOST` | `postgres` | Database host |
| `ENTITY_DS_DB_PORT` | `5432` | Database port |
| `ENTITY_DS_DB_NAME` | `headless_erp` | Database name |
| `ENTITY_DS_DB_USER` | `headless_erp` | Database user |
| `ENTITY_DS_DB_PASSWORD` | `headless_erp` | Database password |
| `JAVA_OPTS` | `-Xms512m -Xmx1024m` | JVM flags |

## Local Development (without Docker)

```bash
# Prerequisites: JDK 21, PostgreSQL 16
./gradlew build
java -Dmoqui.conf=conf/MoquiDevConf.xml -Dmoqui.runtime=runtime -jar moqui.war
```

## Reset Database

```bash
# Docker
docker compose down -v    # removes the database volume
docker compose up -d      # recreates everything

# Local
dropdb headless_erp && createdb headless_erp
./gradlew load
```
