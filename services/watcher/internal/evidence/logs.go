package evidence

import (
	"bytes"
	"context"
	"io"
	"strings"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/client-go/kubernetes"
)

const maxLogChars = 4000

// Reads Previous container logs first (the container has usually already
// restarted by the time an alert fires); "no previous terminated
// container" is a normal condition, not an error, so it retries once
// against the current container.
func FetchLogs(ctx context.Context, clientset kubernetes.Interface, namespace, pod string, tailLines int64) ([]string, error) {
	text, err := fetchLogsOnce(ctx, clientset, namespace, pod, tailLines, true)
	if err != nil {
		if !isPreviousContainerNotFound(err) {
			return nil, err
		}
		text, err = fetchLogsOnce(ctx, clientset, namespace, pod, tailLines, false)
		if err != nil {
			return nil, err
		}
	}

	return capAndSplitLogs(text), nil
}

func capAndSplitLogs(text string) []string {
	if len(text) > maxLogChars {
		text = text[:maxLogChars]
	}
	return strings.Split(text, "\n")
}

func fetchLogsOnce(ctx context.Context, clientset kubernetes.Interface, namespace, pod string, tailLines int64, previous bool) (string, error) {
	req := clientset.CoreV1().Pods(namespace).GetLogs(pod, &corev1.PodLogOptions{
		Previous:  previous,
		TailLines: &tailLines,
	})

	stream, err := req.Stream(ctx)
	if err != nil {
		return "", err
	}
	defer stream.Close()

	var buf bytes.Buffer
	if _, err := io.Copy(&buf, stream); err != nil {
		return "", err
	}
	return buf.String(), nil
}

func isPreviousContainerNotFound(err error) bool {
	msg := err.Error()
	return strings.Contains(msg, "previous terminated container") && strings.Contains(msg, "not found")
}
