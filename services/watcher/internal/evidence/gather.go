package evidence

import (
	"context"
	"errors"

	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"

	"github.com/artanebibi/pharos/services/watcher/internal/model"
)

// Callers must skip diagnosis cleanly on ErrPodVanished rather than call
// /diagnose with empty evidence.
var ErrPodVanished = errors.New("pod vanished")

func Gather(ctx context.Context, clientset kubernetes.Interface, promBaseURL, namespace, pod string, tailLines int64) (model.IncidentContext, error) {
	if _, err := clientset.CoreV1().Pods(namespace).Get(ctx, pod, metav1.GetOptions{}); err != nil {
		if k8serrors.IsNotFound(err) {
			return model.IncidentContext{}, ErrPodVanished
		}
		return model.IncidentContext{}, err
	}

	logs, err := FetchLogs(ctx, clientset, namespace, pod, tailLines)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			return model.IncidentContext{}, ErrPodVanished
		}
		return model.IncidentContext{}, err
	}

	events, err := FetchEvents(ctx, clientset, namespace, pod)
	if err != nil {
		return model.IncidentContext{}, err
	}

	metrics := FetchMetrics(ctx, promBaseURL, namespace, pod)

	return model.IncidentContext{
		PodName:   pod,
		Namespace: namespace,
		Logs:      logs,
		Metrics:   metrics,
		Events:    events,
	}, nil
}
