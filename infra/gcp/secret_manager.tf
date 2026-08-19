data "google_secret_manager_secret" "rag_engine_token" {
  project   = var.project_id
  secret_id = var.rag_engine_token_secret
}

data "google_secret_manager_secret" "gemini_api_key" {
  project   = var.project_id
  secret_id = var.gemini_api_key_secret
}

resource "google_secret_manager_secret_iam_member" "rag_engine_token_accessor" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.rag_engine_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.rag_engine.email}"
}

resource "google_secret_manager_secret_iam_member" "gemini_api_key_accessor" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.gemini_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.rag_engine.email}"
}