package evidence

import (
	"context"
	"fmt"
	"sort"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

const maxEvents = 10

func FetchEvents(ctx context.Context, clientset kubernetes.Interface, namespace, pod string) ([]string, error) {
	list, err := clientset.CoreV1().Events(namespace).List(ctx, metav1.ListOptions{
		FieldSelector: fmt.Sprintf("involvedObject.name=%s", pod),
	})
	if err != nil {
		return nil, err
	}

	// fake.NewSimpleClientset ignores FieldSelector, so filter client-side
	// too; a no-op against a real API server that already filtered.
	items := list.Items[:]
	filtered := items[:0]
	for _, e := range items {
		if e.InvolvedObject.Name == pod {
			filtered = append(filtered, e)
		}
	}

	sort.Slice(filtered, func(i, j int) bool {
		return filtered[i].LastTimestamp.After(filtered[j].LastTimestamp.Time)
	})

	if len(filtered) > maxEvents {
		filtered = filtered[:maxEvents]
	}

	out := make([]string, 0, len(filtered))
	for _, e := range filtered {
		out = append(out, fmt.Sprintf("%s: %s", e.Reason, e.Message))
	}
	return out, nil
}
