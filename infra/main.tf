# El token se lee de VERCEL_API_TOKEN en el entorno; nunca va en el repo.
provider "vercel" {
  team = var.vercel_team_id
}

# Sin recursos hasta la Fase 6.
