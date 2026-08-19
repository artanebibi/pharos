variable "project_id" {
  description = "GCP project hosting the Pharos intelligence plane."
  type        = string
  default     = "pharos-505715"
}

variable "region" {
  description = "Single region for every resource."
  type        = string
  default     = "europe-west3"
}

variable "vertex_location" {
  description = "Region for the Vertex AI embedding endpoint."
  type        = string
  default     = "europe-west3"
}

variable "image_tag" {
  description = "Container image tag, the short git SHA."
  type        = string
  default     = "bootstrap"
}

variable "gemini_model" {
  description = "Gemini model id. Must match the project the API key belongs to."
  type        = string
  default     = "gemini-2.5-flash"
}

variable "ood_floor_threshold" {
  description = "Out-of-distribution escalation floor."
  type        = string
  default     = "0.40"
}

variable "top_k" {
  description = "Number of chunks retrieved per diagnosis."
  type        = string
  default     = "5"
}

variable "firestore_collection" {
  description = "Firestore collection holding the vector corpus."
  type        = string
  default     = "pharos_corpus"
}

variable "rag_engine_token_secret" {
  description = "Secret Manager secret holding the bearer token."
  type        = string
  default     = "pharos-rag-engine-token"
}

variable "gemini_api_key_secret" {
  description = "Secret Manager secret holding the Gemini API key."
  type        = string
  default     = "pharos-gemini-api-key"
}

variable "max_instance_count" {
  description = "Upper bound on Cloud Run instances."
  type        = number
  default     = 3
}
