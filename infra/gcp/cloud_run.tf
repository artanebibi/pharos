locals {
  artifact_registry_url = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.pharos.repository_id}"
  image                 = "${local.artifact_registry_url}/pharos-rag-engine:${var.image_tag}"

  backend_env = {
    EMBEDDER_BACKEND       = "vertex"
    RETRIEVER_BACKEND      = "firestore"
    INCIDENT_STORE_BACKEND = "noop"
    GCP_PROJECT            = var.project_id
    VERTEX_LOCATION        = var.vertex_location
    FIRESTORE_DATABASE     = google_firestore_database.default.name
    FIRESTORE_COLLECTION   = var.firestore_collection
    TOP_K                  = var.top_k
    OOD_FLOOR_THRESHOLD    = var.ood_floor_threshold
  }
}

resource "google_cloud_run_v2_service" "rag_engine" {
  name     = "pharos-rag-engine"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  deletion_protection = false

  template {
    service_account = google_service_account.rag_engine.email
    timeout         = "60s"

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instance_count
    }

    containers {
      image = local.image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      dynamic "env" {
        for_each = local.backend_env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name  = "REASONER_BACKEND"
        value = "gemini"
      }

      env {
        name  = "GEMINI_MODEL"
        value = var.gemini_model
      }

      env {
        name  = "DIAGNOSE_LOG_PATH"
        value = "/tmp/pharos/diagnose_log.jsonl"
      }

      env {
        name = "PHAROS_RAG_ENGINE_TOKEN"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.rag_engine_token.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.rag_engine_token_accessor,
    google_secret_manager_secret_iam_member.gemini_api_key_accessor,
    google_project_iam_member.rag_engine_aiplatform,
    google_project_iam_member.rag_engine_firestore,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.rag_engine.location
  name     = google_cloud_run_v2_service.rag_engine.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}