terraform {
  required_version = ">= 1.6"
  required_providers {
    google = { source = "hashicorp/google", version = ">= 6.0, < 8.0" }
  }
}
provider "google" {
  project = var.gcp_project_id
  region  = var.region
}
resource "google_service_account" "worker" {
  account_id = "worldfoundry-worker"
}
resource "google_service_account" "dispatcher" {
  account_id = "worldfoundry-dispatch"
}
resource "google_service_account" "task_invoker" {
  account_id = "worldfoundry-task"
}
resource "google_cloud_tasks_queue" "runs" {
  name     = "worldfoundry-runs"
  location = var.region
  rate_limits {
    max_dispatches_per_second = 1
    max_concurrent_dispatches = 2
  }
  retry_config {
    max_attempts  = 5
    max_backoff   = "300s"
    min_backoff   = "10s"
    max_doublings = 4
  }
}
resource "google_cloud_tasks_queue_iam_member" "enqueue" {
  project  = var.gcp_project_id
  location = var.region
  name     = google_cloud_tasks_queue.runs.name
  role     = "roles/cloudtasks.enqueuer"
  member   = format("serviceAccount:%s", google_service_account.dispatcher.email)
}
resource "google_cloud_run_v2_service" "worker" {
  name     = "worldfoundry-worker"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"
  template {
    service_account                 = google_service_account.worker.email
    timeout                         = "600s"
    max_instance_request_concurrency = 1
    scaling { max_instance_count = 2 }
    containers {
      image = var.image
      resources { limits = { cpu = "1", memory = "512Mi" } }
      env {
        name  = "SUPABASE_URL"
        value = var.supabase_url
      }
      env {
        name = "SUPABASE_SERVICE_ROLE_KEY"
        value_source {
          secret_key_ref {
            secret  = var.supabase_secret_name
            version = "latest"
          }
        }
      }
      env {
        name = "WF_WORKER_SHARED_TOKEN"
        value_source {
          secret_key_ref {
            secret  = var.worker_token_secret_name
            version = "latest"
          }
        }
      }
    }
  }
}
resource "google_cloud_run_v2_service_iam_member" "task_invoker" {
  project  = var.gcp_project_id
  location = var.region
  name     = google_cloud_run_v2_service.worker.name
  role     = "roles/run.invoker"
  member   = format("serviceAccount:%s", google_service_account.task_invoker.email)
}
resource "google_secret_manager_secret_iam_member" "worker_supabase" {
  project   = var.gcp_project_id
  secret_id = var.supabase_secret_name
  role      = "roles/secretmanager.secretAccessor"
  member    = format("serviceAccount:%s", google_service_account.worker.email)
}
resource "google_secret_manager_secret_iam_member" "worker_token" {
  project   = var.gcp_project_id
  secret_id = var.worker_token_secret_name
  role      = "roles/secretmanager.secretAccessor"
  member    = format("serviceAccount:%s", google_service_account.worker.email)
}
output "worker_url" { value = google_cloud_run_v2_service.worker.uri }
output "queue_name" { value = google_cloud_tasks_queue.runs.name }
output "dispatcher_account" { value = google_service_account.dispatcher.email }
output "task_invoker_account" { value = google_service_account.task_invoker.email }
