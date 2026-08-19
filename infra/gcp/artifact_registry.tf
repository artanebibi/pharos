resource "google_artifact_registry_repository" "pharos" {
  location      = var.region
  repository_id = "pharos"
  description   = "Pharos container images (rag-engine, shared by the indexer job)."
  format        = "DOCKER"
}
