# Plan: Azure IaC with Terraform + Container Apps

## Goal

Host the Kanaliiga Fantasy League on Azure using Infrastructure-as-Code so the environment is reproducible and teardown/redeploy is a single command. Target: demo-ready HTTPS URL in 4 commands.

## Architecture

| Component | Azure service | Why |
|---|---|---|
| Compute | **Container Apps** | Serverless, managed HTTPS, free tier, scales to zero |
| Storage | **Azure Files (File Share)** | Persistent volume for SQLite — survives container restarts |
| Observability | **Log Analytics Workspace** | Required by Container Apps; captures stdout logs |
| Registry | **GitHub Container Registry** | Already used by CI/CD (`ghcr.io`) |

All resources live in one Resource Group for easy cleanup.

## The 4 Commands

```bash
# 1. Authenticate with Azure
az login

# 2. Initialise Terraform (downloads provider plugins)
cd infra && terraform init

# 3. Deploy all resources (~3 minutes)
terraform apply -var="github_repository=<owner>/<repo>"

# 4. Open the live URL printed by Terraform
# e.g. https://kanaliiga-fantasy.<hash>.swedencentral.azurecontainerapps.io
```

## Files

- `infra/main.tf` — all 5 Terraform resources + variables + output

## Key Variables

| Variable | Default | Description |
|---|---|---|
| `github_repository` | *(required)* | `owner/repo` for the GHCR image |
| `location` | `swedencentral` | Azure region |
| `app_name` | `kanaliiga-fantasy` | Prefix for all resource names |
| `image_tag` | `latest` | Container image tag to deploy |
| `season_lock_start` | `2026-03-08` | First Sunday lock anchor |
| `token_name` | `Kana Tokens` | In-game currency display name |
| `initial_tokens` | `5` | Tokens granted on registration |
| `auto_ingest_leagues` | `19368,19369` | League IDs to ingest on startup |
| `schedule_sheet_url` | `""` | Google Sheets CSV URL |

## Persistence

SQLite is stored at `/data/fantasy.db` inside the container. The `/data` directory is backed by an Azure File Share (`fantasy-data`, 5 GB quota) mounted via the Container App Environment storage binding. Data survives container restarts and redeployments.

## Teardown

```bash
terraform destroy
```

Removes all Azure resources. The File Share (and its SQLite data) is deleted with the storage account.

## Prerequisites

- Azure CLI (`az`) installed and a subscription available
- Terraform ≥ 1.5 installed
- Docker image pushed to `ghcr.io/<owner>/<repo>:latest` (done by CI/CD on push to `main`)
- Public GHCR visibility OR Azure Container App configured with a registry credential

## Cost Estimate (demo / low traffic)

| Resource | Free tier / cost |
|---|---|
| Container Apps | Free up to 180,000 vCPU-s/month — zero cost for demos |
| Log Analytics | First 5 GB/month free |
| Storage Account | ~€0.02/GB/month — negligible for 5 GB |
| **Total** | **~€0 for demo use** |
