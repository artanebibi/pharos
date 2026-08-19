resource "google_cloud_run_v2_job" "indexer" {
  name     = "pharos-indexer"
  location = var.region

  deletion_protection = false

  template {
    template {
      service_account       = google_service_account.rag_engine.email
      max_retries           = 0
      timeout               = "900s"
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

      containers {
        image = local.image

        command = ["python", "/app/services/indexer/main.py"]

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
      }
    }
  }

  depends_on = [
    google_project_iam_member.rag_engine_aiplatform,
    google_project_iam_member.rag_engine_firestore,
    google_firestore_index.corpus_embedding,
  ]
}
