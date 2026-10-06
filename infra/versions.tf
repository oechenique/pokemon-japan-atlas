# Terraform base (Fase 0): providers fijados, state local, sin recursos ni credenciales.
# Los recursos (proyecto de Vercel) llegan en la Fase 6. Cloudflare R2 solo se
# agrega si se activa, y se pregunta antes (reglas/00, contrato pipeline → web).
terraform {
  required_version = ">= 1.9"

  backend "local" {
    path = "terraform.tfstate"
  }

  required_providers {
    vercel = {
      source  = "vercel/vercel"
      version = "~> 5.19"
    }
  }
}
