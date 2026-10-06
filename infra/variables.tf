variable "project_name" {
  description = "Nombre del proyecto en Vercel."
  type        = string
  default     = "pokemon-japan-atlas"
}

variable "vercel_team_id" {
  description = "Team de Vercel. Null usa la cuenta personal."
  type        = string
  default     = null
}
