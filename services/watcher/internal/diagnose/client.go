package diagnose

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/artanebibi/pharos/services/watcher/internal/model"
)

const requestTimeout = 30 * time.Second

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

// Diagnosis is nil on non-2xx or a decode failure; StatusCode/RawBody are
// always set so callers can log the full response either way.
type Result struct {
	StatusCode int
	RawBody    string
	Diagnosis  *model.Diagnosis
}

func (c *Client) Diagnose(ctx context.Context, incident model.IncidentContext) (*Result, error) {
	ctx, cancel := context.WithTimeout(ctx, requestTimeout)
	defer cancel()

	body, err := json.Marshal(incident)
	if err != nil {
		return nil, fmt.Errorf("diagnose: marshal incident: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.BaseURL+"/diagnose", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("diagnose: build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("diagnose: request failed: %w", err)
	}
	defer resp.Body.Close()

	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("diagnose: read response: %w", err)
	}

	result := &Result{StatusCode: resp.StatusCode, RawBody: string(raw)}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return result, fmt.Errorf("diagnose: non-2xx status %d: %s", resp.StatusCode, string(raw))
	}

	var d model.Diagnosis
	if err := json.Unmarshal(raw, &d); err != nil {
		return result, fmt.Errorf("diagnose: decode response: %w", err)
	}
	result.Diagnosis = &d

	return result, nil
}
