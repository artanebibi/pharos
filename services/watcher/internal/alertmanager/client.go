package alertmanager

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
)

type Alert struct {
	Fingerprint string
	Labels      map[string]string
}

type rawStatus struct {
	State string `json:"state"`
}

type rawAlert struct {
	Fingerprint string            `json:"fingerprint"`
	Labels      map[string]string `json:"labels"`
	Status      rawStatus         `json:"status"`
}

type Client struct {
	BaseURL    string
	HTTPClient *http.Client
}

func New(baseURL string) *Client {
	return &Client{
		BaseURL:    baseURL,
		HTTPClient: &http.Client{},
	}
}

// "active" is AlertManager's word for "firing".
func (c *Client) ActiveAlerts(ctx context.Context) ([]Alert, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.BaseURL+"/api/v2/alerts", nil)
	if err != nil {
		return nil, fmt.Errorf("alertmanager: build request: %w", err)
	}

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("alertmanager: request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("alertmanager: unexpected status %d", resp.StatusCode)
	}

	var raw []rawAlert
	if err := json.NewDecoder(resp.Body).Decode(&raw); err != nil {
		return nil, fmt.Errorf("alertmanager: decode response: %w", err)
	}

	active := make([]Alert, 0, len(raw))
	for _, a := range raw {
		if a.Status.State != "active" {
			continue
		}
		active = append(active, Alert{
			Fingerprint: a.Fingerprint,
			Labels:      a.Labels,
		})
	}
	return active, nil
}
