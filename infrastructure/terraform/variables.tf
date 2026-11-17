variable "gcp_project_id" { type = string }
variable "region" { type = string, default = "us-central1" }
variable "image" {
  type = string
  description = "Immutable tested Artifact Registry image, preferably @sha256 digest"
}
variable "supabase_url" { type = string }
variable "supabase_secret_name" { type = string, default = "wf-supabase-service-role" }
variable "worker_token_secret_name" { type = string, default = "wf-worker-token" }
