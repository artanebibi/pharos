package watcher

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"slices"
	"time"

	"k8s.io/client-go/kubernetes"

	"github.com/artanebibi/pharos/services/watcher/internal/alertmanager"
	"github.com/artanebibi/pharos/services/watcher/internal/dedup"
	"github.com/artanebibi/pharos/services/watcher/internal/diagnose"
	"github.com/artanebibi/pharos/services/watcher/internal/evidence"
)

// One line of tests/logs/watcher_log.jsonl — do not drop fields, this is
type LogEntry struct {
	Timestamp      string            `json:"timestamp"`
	Fingerprint    string            `json:"fingerprint"`
	Labels         map[string]string `json:"labels"`
	Evidence       any               `json:"evidence"`
	DiagnoseStatus int               `json:"diagnose_status,omitempty"`
	Diagnosis      any               `json:"diagnosis,omitempty"`
	IncidentID     *string           `json:"incident_id"`
	Error          string            `json:"error,omitempty"`
	PodVanished    bool              `json:"pod_vanished,omitempty"`
	Reason         string            `json:"reason,omitempty"`
}

type Loop struct {
	AM               *alertmanager.Client
	K8s              kubernetes.Interface
	PrometheusURL    string
	Diag             *diagnose.Client
	Dedup            *dedup.Tracker
	DedupTTL         time.Duration
	LogTailLines     int64
	LogEncoder       *json.Encoder
	NamespaceFilters []string
}

func (l *Loop) RunOnce(ctx context.Context) error {
	l.Dedup.Prune(l.DedupTTL)

	alerts, err := l.AM.ActiveAlerts(ctx)
	if err != nil {
		return err
	}

	for _, alert := range alerts {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		l.processAlert(ctx, alert)
	}
	return nil
}

func (l *Loop) processAlert(ctx context.Context, alert alertmanager.Alert) {
	if l.Dedup.IsFresh(alert.Fingerprint, l.DedupTTL) {
		return
	}

	entry := LogEntry{
		Timestamp:   time.Now().UTC().Format(time.RFC3339),
		Fingerprint: alert.Fingerprint,
		Labels:      alert.Labels,
		Evidence:    map[string]any{},
	}

	namespace := alert.Labels["namespace"]
	pod := alert.Labels["pod"]

	if len(l.NamespaceFilters) > 0 && !slices.Contains(l.NamespaceFilters, namespace) {
		entry.Reason = "namespace_filter"
		l.writeLog(entry)
		l.Dedup.MarkSeen(alert.Fingerprint)
		return
	}

	// Cluster-wide alerts (Watchdog, TargetDown) have no namespace/pod;
	// mark seen so they don't spam the log every poll cycle forever.
	if namespace == "" || pod == "" {
		entry.Error = "not pod-scoped: alert has no namespace/pod label, skipping"
		l.writeLog(entry)
		l.Dedup.MarkSeen(alert.Fingerprint)
		return
	}

	incident, err := evidence.Gather(ctx, l.K8s, l.PrometheusURL, namespace, pod, l.LogTailLines)
	if err != nil {
		if errors.Is(err, evidence.ErrPodVanished) {
			entry.PodVanished = true
			l.writeLog(entry)
			log.Printf("pod_vanished fingerprint=%s namespace=%s pod=%s", alert.Fingerprint, namespace, pod)
			return
		}
		entry.Error = err.Error()
		l.writeLog(entry)
		log.Printf("evidence gather failed fingerprint=%s: %v", alert.Fingerprint, err)
		return
	}
	entry.Evidence = incident

	result, err := l.Diag.Diagnose(ctx, incident)
	if result != nil {
		entry.DiagnoseStatus = result.StatusCode
	}
	if err != nil {
		entry.Error = err.Error()
		l.writeLog(entry)
		log.Printf("diagnose failed fingerprint=%s: %v", alert.Fingerprint, err)
		return // no MarkSeen: next poll retries
	}

	entry.Diagnosis = result.Diagnosis
	entry.IncidentID = strPtrOrNil(result.Diagnosis.IncidentID)
	l.writeLog(entry)
	log.Printf("diagnosis fingerprint=%s root_cause=%q incident_id=%s",
		alert.Fingerprint, result.Diagnosis.RootCause, result.Diagnosis.IncidentID)
	l.Dedup.MarkSeen(alert.Fingerprint)
}

func strPtrOrNil(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func (l *Loop) writeLog(entry LogEntry) {
	if l.LogEncoder == nil {
		return
	}
	if err := l.LogEncoder.Encode(entry); err != nil {
		log.Printf("watcher: failed to write log entry: %v", err)
	}
}
