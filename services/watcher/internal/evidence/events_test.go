package evidence

import (
	"context"
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes/fake"
)

func mkEvent(name string, ts time.Time, reason, message, podName string) *corev1.Event {
	return &corev1.Event{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: "workloads"},
		InvolvedObject: corev1.ObjectReference{
			Name:      podName,
			Namespace: "workloads",
		},
		Reason:        reason,
		Message:       message,
		LastTimestamp: metav1.NewTime(ts),
	}
}

func TestFetchEvents_ReturnsFormattedSortedRecent(t *testing.T) {
	base := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

	clientset := fake.NewSimpleClientset(
		mkEvent("e1", base, "Started", "Started container", "crashloop-demo-1"),
		mkEvent("e2", base.Add(time.Minute), "BackOff", "Back-off restarting failed container", "crashloop-demo-1"),
		mkEvent("e3", base.Add(2*time.Minute), "Unrelated", "event for a different pod", "some-other-pod"),
	)

	events, err := FetchEvents(context.Background(), clientset, "workloads", "crashloop-demo-1")
	if err != nil {
		t.Fatalf("FetchEvents error: %v", err)
	}

	if len(events) != 2 {
		t.Fatalf("expected 2 events for crashloop-demo-1, got %d: %v", len(events), events)
	}

	if events[0] != "BackOff: Back-off restarting failed container" {
		t.Errorf("expected most recent event first, got %q", events[0])
	}
	if events[1] != "Started: Started container" {
		t.Errorf("expected oldest event last, got %q", events[1])
	}
}

func TestFetchEvents_CapsAtTen(t *testing.T) {
	base := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

	objs := make([]runtime.Object, 0, 15)
	for i := 0; i < 15; i++ {
		name := "ev" + string(rune('a'+i))
		objs = append(objs, mkEvent(name, base.Add(time.Duration(i)*time.Minute), "Reason", "msg", "crashloop-demo-1"))
	}

	clientset := fake.NewSimpleClientset(objs...)

	events, err := FetchEvents(context.Background(), clientset, "workloads", "crashloop-demo-1")
	if err != nil {
		t.Fatalf("FetchEvents error: %v", err)
	}
	if len(events) != 10 {
		t.Fatalf("expected events capped at 10, got %d", len(events))
	}
}
