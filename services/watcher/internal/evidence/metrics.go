package evidence

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
)

type promQueryResponse struct {
	Status string `json:"status"`
	Data   struct {
		ResultType string `json:"resultType"`
		Result     []struct {
			Metric map[string]string  `json:"metric"`
			Value  [2]json.RawMessage `json:"value"`
		} `json:"result"`
	} `json:"data"`
}

// A query returning no data or erroring omits its key rather than
// inventing a zero, and never fails the other two queries.
func FetchMetrics(ctx context.Context, promBaseURL, namespace, pod string) map[string]float64 {
	queries := map[string]string{
		"restart_count": fmt.Sprintf(
			`kube_pod_container_status_restarts_total{namespace="%s", pod="%s"}`,
			namespace, pod),
		"memory_working_set_ratio": fmt.Sprintf(
			`container_memory_working_set_bytes{namespace="%s", pod="%s", container!="POD", container!=""} / on(pod, namespace, container) group_left kube_pod_container_resource_limits{resource="memory", namespace="%s", pod="%s"}`,
			namespace, pod, namespace, pod),
		"cpu_throttle_ratio": fmt.Sprintf(
			`rate(container_cpu_cfs_throttled_periods_total{namespace="%s", pod="%s"}[5m]) / rate(container_cpu_cfs_periods_total{namespace="%s", pod="%s"}[5m])`,
			namespace, pod, namespace, pod),
	}

	metrics := make(map[string]float64)
	for key, query := range queries {
		val, ok, err := queryPrometheusScalar(ctx, promBaseURL, query)
		if err != nil || !ok {
			continue
		}
		metrics[key] = val
	}
	return metrics
}

func queryPrometheusScalar(ctx context.Context, baseURL, query string) (float64, bool, error) {
	u := baseURL + "/api/v1/query?" + url.Values{"query": {query}}.Encode()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return 0, false, fmt.Errorf("metrics: build request: %w", err)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, false, fmt.Errorf("metrics: request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return 0, false, fmt.Errorf("metrics: unexpected status %d", resp.StatusCode)
	}

	var parsed promQueryResponse
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return 0, false, fmt.Errorf("metrics: decode response: %w", err)
	}

	if len(parsed.Data.Result) == 0 {
		return 0, false, nil
	}

	var valStr string
	if err := json.Unmarshal(parsed.Data.Result[0].Value[1], &valStr); err != nil {
		return 0, false, fmt.Errorf("metrics: decode value: %w", err)
	}

	f, err := strconv.ParseFloat(valStr, 64)
	if err != nil {
		return 0, false, fmt.Errorf("metrics: parse value: %w", err)
	}
	return f, true, nil
}
