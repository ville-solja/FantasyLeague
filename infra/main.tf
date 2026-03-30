terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

# -------------------------------------------------------
# Variables
# -------------------------------------------------------

variable "resource_group_name" {
  default = "kanaliiga-fantasy-rg"
}

variable "location" {
  default = "swedencentral"
}

variable "app_name" {
  default = "kanaliiga-fantasy"
}

variable "github_repository" {
  description = "GitHub repo in owner/repo format, e.g. ville-solja/FantasyLeague"
}

variable "image_tag" {
  default = "latest"
}

variable "season_lock_start" {
  description = "First Sunday lock date, e.g. 2026-03-08"
  default     = "2026-03-08"
}

variable "token_name" {
  default = "Kana Tokens"
}

variable "initial_tokens" {
  default = "5"
}

variable "auto_ingest_leagues" {
  default = "19368,19369"
}

variable "schedule_sheet_url" {
  default = ""
}

# -------------------------------------------------------
# Resource Group
# -------------------------------------------------------

resource "azurerm_resource_group" "rg" {
  name     = var.resource_group_name
  location = var.location
}

# -------------------------------------------------------
# Log Analytics Workspace (required by Container Apps)
# -------------------------------------------------------

resource "azurerm_log_analytics_workspace" "law" {
  name                = "${var.app_name}-law"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

# -------------------------------------------------------
# Storage Account + File Share (SQLite persistence)
# -------------------------------------------------------

resource "azurerm_storage_account" "sa" {
  name                     = replace("${var.app_name}sa", "-", "")
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

resource "azurerm_storage_share" "data" {
  name                 = "fantasy-data"
  storage_account_name = azurerm_storage_account.sa.name
  quota                = 5  # GB
}

# -------------------------------------------------------
# Container App Environment
# -------------------------------------------------------

resource "azurerm_container_app_environment" "env" {
  name                       = "${var.app_name}-env"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
}

resource "azurerm_container_app_environment_storage" "data_mount" {
  name                         = "fantasy-data"
  container_app_environment_id = azurerm_container_app_environment.env.id
  account_name                 = azurerm_storage_account.sa.name
  share_name                   = azurerm_storage_share.data.name
  access_key                   = azurerm_storage_account.sa.primary_access_key
  access_mode                  = "ReadWrite"
}

# -------------------------------------------------------
# Container App
# -------------------------------------------------------

resource "azurerm_container_app" "app" {
  name                         = var.app_name
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = "Single"

  template {
    container {
      name   = "fantasy"
      image  = "ghcr.io/${var.github_repository}:${var.image_tag}"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "DATABASE_URL"
        value = "sqlite:////data/fantasy.db"
      }
      env {
        name  = "SEASON_LOCK_START"
        value = var.season_lock_start
      }
      env {
        name  = "TOKEN_NAME"
        value = var.token_name
      }
      env {
        name  = "INITIAL_TOKENS"
        value = var.initial_tokens
      }
      env {
        name  = "AUTO_INGEST_LEAGUES"
        value = var.auto_ingest_leagues
      }
      env {
        name  = "SCHEDULE_SHEET_URL"
        value = var.schedule_sheet_url
      }

      volume_mounts {
        name = "data"
        path = "/data"
      }
    }

    volume {
      name         = "data"
      storage_type = "AzureFile"
      storage_name = azurerm_container_app_environment_storage.data_mount.name
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

# -------------------------------------------------------
# Outputs
# -------------------------------------------------------

output "app_url" {
  description = "Public HTTPS URL of the deployed fantasy league"
  value       = "https://${azurerm_container_app.app.ingress[0].fqdn}"
}
