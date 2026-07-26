package watcher

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"sync/atomic"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"

	"github.com/artanebibi/pharos/services/watcher/internal/alertmanager"
	"github.com/artanebibi/pharos/services/watcher/internal/dedup"
	"github.com/artanebibi/pharos/services/watcher/internal/diagnose"
)

const unreachablePrometheus = "http://127.0.0.1:1"

func newTempLogEncoder(t *testing.T) (*json.Encoder, string) {
	t.Helper()
	f, err := os.CreateTemp(t.TempDir(), "watcher_log_*.jsonl")
	if err != nil {
		t.Fatalf("create temp log file: %v", err)
	}
	t.Cleanup(func() { f.Close() })
	return json.NewEncoder(f), f.Name()
}

func TestRunOnce_DiagnosesThenDedups(t *testing.T) {
	amAlerts := `[
	  {"fingerprint": "fp-crashloop", "labels": {"alertname": "PodCrashLoopBackOff", "namespace": "workloads", "pod": "crashloop-demo-1"}, "status": {"state": "active"}}
	]`
	amSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(amAlerts))
	}))
	defer amSrv.Close()

	var diagnoseCalls int32
	diagSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&diagnoseCalls, 1)
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{
			"root_cause":                "missing config",
			"retrieval_relevance_score": 0.7,
			"severity":                  "high",
			"remediation_steps":         []string{"restart"},
			"kubectl_commands":          []string{"kubectl rollout restart deploy/crashloop-demo"},
			"sources_used":              []string{"crashloop-backoff.md::Remediation"},
			"reasoning":                 "test",
		})
	}))
	defer diagSrv.Close()

	clientset := fake.NewSimpleClientset(&corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{Name: "crashloop-demo-1", Namespace: "workloads"},
	})

	enc, _ := newTempLogEncoder(t)

	loop := &Loop{
		AM:            alertmanager.New(amSrv.URL),
		K8s:           clientset,
		PrometheusURL: unreachablePrometheus,
		Diag:          diagnose.New(diagSrv.URL),
		Dedup:         dedup.New(time.Now),
		DedupTTL:      15 * time.Minute,
		LogTailLines:  200,
		LogEncoder:    enc,
	}

	ctx := context.Background()

	if err := loop.RunOnce(ctx); err != nil {
		t.Fatalf("first RunOnce error: %v", err)
	}
	if got := atomic.LoadInt32(&diagnoseCalls); got != 1 {
		t.Fatalf("expected 1 diagnose call after first cycle, got %d", got)
	}

	if err := loop.RunOnce(ctx); err != nil {
		t.Fatalf("second RunOnce error: %v", err)
	}
	if got := atomic.LoadInt32(&diagnoseCalls); got != 1 {
		t.Fatalf("expected still 1 diagnose call after second cycle (dedup), got %d", got)
	}
}

func TestRunOnce_NamespaceFilter_SkipsNonMatchingNamespace(t *testing.T) {
	amAlerts := `[
	  {"fingerprint": "fp-kube-system", "labels": {"alertname": "KubeProxyInstanceUnreachable", "namespace": "kube-system", "pod": "kube-proxy-abc"}, "status": {"state": "active"}}
	]`
	amSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(amAlerts))
	}))
	defer amSrv.Close()

	var diagnoseCalls int32
	diagSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&diagnoseCalls, 1)
		w.WriteHeader(http.StatusOK)
	}))
	defer diagSrv.Close()

	clientset := fake.NewSimpleClientset()
	enc, logPath := newTempLogEncoder(t)

	loop := &Loop{
		AM:               alertmanager.New(amSrv.URL),
		K8s:              clientset,
		PrometheusURL:    unreachablePrometheus,
		Diag:             diagnose.New(diagSrv.URL),
		Dedup:            dedup.New(time.Now),
		DedupTTL:         15 * time.Minute,
		LogTailLines:     200,
		LogEncoder:       enc,
		NamespaceFilters: []string{"workloads"},
	}

	if err := loop.RunOnce(context.Background()); err != nil {
		t.Fatalf("first RunOnce error: %v", err)
	}
	if err := loop.RunOnce(context.Background()); err != nil {
		t.Fatalf("second RunOnce error: %v", err)
	}

	if got := atomic.LoadInt32(&diagnoseCalls); got != 0 {
		t.Fatalf("expected 0 diagnose calls for a namespace-filtered alert, got %d", got)
	}

	data, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read log file: %v", err)
	}
	if !bytes.Contains(data, []byte(`"reason":"namespace_filter"`)) {
		t.Fatalf("expected reason:namespace_filter in log, got: %s", data)
	}
	if !bytes.Contains(data, []byte(`"incident_id":null`)) {
		t.Fatalf("expected incident_id:null in log, got: %s", data)
	}
	if got := bytes.Count(data, []byte(`"reason":"namespace_filter"`)); got != 1 {
		t.Fatalf("expected exactly 1 namespace_filter skip entry (dedup should suppress the second cycle), got %d", got)
	}
}

func TestRunOnce_PodVanished_NoDiagnoseNoPanic(t *testing.T) {
	amAlerts := `[
	  {"fingerprint": "fp-vanished", "labels": {"alertname": "PodCrashLoopBackOff", "namespace": "workloads", "pod": "ghost-pod"}, "status": {"state": "active"}}
	]`
	amSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(amAlerts))
	}))
	defer amSrv.Close()

	var diagnoseCalls int32
	diagSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&diagnoseCalls, 1)
		w.WriteHeader(http.StatusOK)
	}))
	defer diagSrv.Close()

	clientset := fake.NewSimpleClientset() // no pods seeded -> NotFound

	enc, logPath := newTempLogEncoder(t)

	loop := &Loop{
		AM:            alertmanager.New(amSrv.URL),
		K8s:           clientset,
		PrometheusURL: unreachablePrometheus,
		Diag:          diagnose.New(diagSrv.URL),
		Dedup:         dedup.New(time.Now),
		DedupTTL:      15 * time.Minute,
		LogTailLines:  200,
		LogEncoder:    enc,
	}

	if err := loop.RunOnce(context.Background()); err != nil {
		t.Fatalf("RunOnce error: %v", err)
	}

	if got := atomic.LoadInt32(&diagnoseCalls); got != 0 {
		t.Fatalf("expected 0 diagnose calls for a vanished pod, got %d", got)
	}

	data, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read log file: %v", err)
	}
	if !bytes.Contains(data, []byte(`"pod_vanished":true`)) {
		t.Fatalf("expected pod_vanished:true in log, got: %s", data)
	}
}
