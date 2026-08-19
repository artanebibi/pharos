resource "google_service_account" "rag_engine" {
  account_id   = "pharos-rag-engine"
  display_name = "Pharos RAG engine (Cloud Run service + indexer job)"
  description  = "Least-privilege identity for the RAG engine. Attached directly by Cloud Run; no key is created."
}

resource "google_project_iam_member" "rag_engine_aiplatform" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.rag_engine.email}"
}

resource "google_project_iam_member" "rag_engine_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.rag_engine.email}"
}