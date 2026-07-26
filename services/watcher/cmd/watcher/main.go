package main

import (
	"context"
	"encoding/json"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"

	"github.com/artanebibi/pharos/services/watcher/internal/alertmanager"
	"github.com/artanebibi/pharos/services/watcher/internal/config"
	"github.com/artanebibi/pharos/services/watcher/internal/dedup"
	"github.com/artanebibi/pharos/services/watcher/internal/diagnose"
	"github.com/artanebibi/pharos/services/watcher/internal/watcher"
)

func main() {
	cfg := config.Load()

	if err := os.MkdirAll(filepath.Dir(cfg.WatcherLogPath), 0o755); err != nil {
		log.Fatalf("watcher: create log dir: %v", err)
	}
	logFile, err := os.OpenFile(cfg.WatcherLogPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		log.Fatalf("watcher: open log file: %v", err)
	}
	defer logFile.Close()

	kubeConfig, err := buildKubeConfig()
	if err != nil {
		log.Fatalf("watcher: build kube config: %v", err)
	}
	clientset, err := kubernetes.NewForConfig(kubeConfig)
	if err != nil {
		log.Fatalf("watcher: build k8s client: %v", err)
	}

	loop := &watcher.Loop{
		AM:               alertmanager.New(cfg.AlertManagerURL),
		K8s:              clientset,
		PrometheusURL:    cfg.PrometheusURL,
		Diag:             diagnose.New(cfg.RAGEngineURL),
		Dedup:            dedup.New(time.Now),
		DedupTTL:         cfg.DedupTTL,
		LogTailLines:     cfg.LogTailLines,
		LogEncoder:       json.NewEncoder(logFile),
		NamespaceFilters: cfg.NamespaceFilters,
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	log.Printf("watcher started poll_interval=%s", cfg.PollInterval)

	if err := loop.RunOnce(ctx); err != nil {
		log.Printf("watcher: poll cycle error: %v", err)
	}

	ticker := time.NewTicker(cfg.PollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Printf("watcher: shutting down")
			return
		case <-ticker.C:
			if err := loop.RunOnce(ctx); err != nil {
				log.Printf("watcher: poll cycle error: %v", err)
			}
		}
	}
}

func buildKubeConfig() (*rest.Config, error) {
	rules := clientcmd.NewDefaultClientConfigLoadingRules()
	overrides := &clientcmd.ConfigOverrides{}
	return clientcmd.NewNonInteractiveDeferredLoadingClientConfig(rules, overrides).ClientConfig()
}
