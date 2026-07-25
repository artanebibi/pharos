package alertmanager

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

const fixtureJSON = `[
  {
    "fingerprint": "aaa111",
    "labels": {"alertname": "PodCrashLoopBackOff", "namespace": "workloads", "pod": "crashloop-demo-1"},
    "status": {"state": "active"}
  },
  {
    "fingerprint": "bbb222",
    "labels": {"alertname": "PodOOMKilled", "namespace": "workloads", "pod": "oom-demo-1"},
    "status": {"state": "active"}
  },
  {
    "fingerprint": "ccc333",
    "labels": {"alertname": "PodCPUThrottlingHigh", "namespace": "workloads", "pod": "cpu-demo-1"},
    "status": {"state": "resolved"}
  }
]`

func TestActiveAlerts_FiltersToActiveOnly(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v2/alerts" {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(fixtureJSON))
	}))
	defer srv.Close()

	c := New(srv.URL)
	alerts, err := c.ActiveAlerts(context.Background())
	if err != nil {
		t.Fatalf("ActiveAlerts returned error: %v", err)
	}

	if len(alerts) != 2 {
		t.Fatalf("expected 2 active alerts, got %d", len(alerts))
	}

	if alerts[0].Fingerprint != "aaa111" {
		t.Errorf("alert 0: expected fingerprint aaa111, got %s", alerts[0].Fingerprint)
	}
	if alerts[0].Labels["alertname"] != "PodCrashLoopBackOff" {
		t.Errorf("alert 0: unexpected labels: %v", alerts[0].Labels)
	}

	if alerts[1].Fingerprint != "bbb222" {
		t.Errorf("alert 1: expected fingerprint bbb222, got %s", alerts[1].Fingerprint)
	}
	if alerts[1].Labels["alertname"] != "PodOOMKilled" {
		t.Errorf("alert 1: unexpected labels: %v", alerts[1].Labels)
	}

	for _, a := range alerts {
		if a.Fingerprint == "ccc333" {
			t.Errorf("resolved alert ccc333 should have been filtered out")
		}
	}
}
