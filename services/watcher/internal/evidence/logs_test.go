package evidence

import (
	"context"
	"strings"
	"testing"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

func TestCapAndSplitLogs_CapsAt4000CharsAndSplitsOnNewline(t *testing.T) {
	long := strings.Repeat("a", 5000)
	lines := capAndSplitLogs(long)
	joined := strings.Join(lines, "")
	if len(joined) != maxLogChars {
		t.Fatalf("expected capped length %d, got %d", maxLogChars, len(joined))
	}

	multi := "line1\nline2\nline3"
	lines = capAndSplitLogs(multi)
	if len(lines) != 3 || lines[0] != "line1" || lines[2] != "line3" {
		t.Fatalf("expected 3 split lines, got %v", lines)
	}
}

func TestFetchLogs_NoPanicAgainstFakeClientset(t *testing.T) {
	clientset := fake.NewSimpleClientset(&corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{Name: "crashloop-demo-1", Namespace: "workloads"},
	})

	lines, err := FetchLogs(context.Background(), clientset, "workloads", "crashloop-demo-1", 200)
	if err != nil {
		t.Fatalf("FetchLogs returned unexpected error against fake clientset: %v", err)
	}
	if lines == nil {
		t.Fatalf("expected a non-nil (possibly empty-content) []string, got nil")
	}
}
