resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  delete_protection_state = "DELETE_PROTECTION_ENABLED"
  deletion_policy         = "DELETE"
}

resource "google_firestore_index" "corpus_embedding" {
  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = var.firestore_collection

  fields {
    field_path = "__name__"
    order      = "ASCENDING"
  }

  fields {
    field_path = "embedding"

    vector_config {
      dimension = 768
      flat {}
    }
  }
}