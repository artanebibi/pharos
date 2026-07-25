package model

// JSON tags must match rag-engine/schemas.py's IncidentContext field-for-field;
// the RAG engine rejects unknown fields.
type IncidentContext struct {
	PodName   string             `json:"pod_name"`
	Namespace string             `json:"namespace"`
	Logs      []string           `json:"logs"`
	Metrics   map[string]float64 `json:"metrics"`
	Events    []string           `json:"events"`
}

type Diagnosis struct {
	RootCause               string   `json:"root_cause"`
	RetrievalRelevanceScore float64  `json:"retrieval_relevance_score"`
	Severity                string   `json:"severity"`
	RemediationSteps        []string `json:"remediation_steps"`
	KubectlCommands         []string `json:"kubectl_commands"`
	SourcesUsed             []string `json:"sources_used"`
	Reasoning               string   `json:"reasoning"`
}
