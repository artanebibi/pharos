output "cloud_run_url" {
  description = "Public HTTPS endpoint of the RAG engine. Phase 3's AWS Lambda POSTs /diagnose here."
  value       = google_cloud_run_v2_service.rag_engine.uri
}

output "artifact_registry_url" {
  description = "Docker repository host path - the docker build/push target."
  value       = local.artifact_registry_url
}

output "indexer_job_name" {
  description = "Run with: gcloud run jobs execute <name> --region <region> --wait"
  value       = google_cloud_run_v2_job.indexer.name
}

output "service_account_email" {
  description = "Least-privilege identity shared by the Cloud Run service and the indexer job."
  value       = google_service_account.rag_engine.email
}