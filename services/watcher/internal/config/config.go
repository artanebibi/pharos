package config

import (
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/joho/godotenv"
)

type Config struct {
	PollInterval     time.Duration
	DedupTTL         time.Duration
	LogTailLines     int64
	AlertManagerURL  string
	PrometheusURL    string
	RAGEngineURL     string
	WatcherLogPath   string
	RepoRoot         string
	NamespaceFilters []string
}

// repoRoot walks up from this source file's compile-time location to find the repo root
func repoRoot() string {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		return "."
	}
	dir := filepath.Dir(file)
	for i := 0; i < 4; i++ {
		dir = filepath.Dir(dir)
	}
	return dir
}

func Load() Config {
	root := repoRoot()
	_ = godotenv.Load(filepath.Join(root, ".env"))

	return Config{
		PollInterval:     getEnvSeconds("WATCHER_POLL_INTERVAL_SEC", 15),
		DedupTTL:         getEnvSeconds("DEDUP_TTL_SEC", 900),
		LogTailLines:     getEnvInt64("LOG_TAIL_LINES", 200),
		AlertManagerURL:  getEnvStr("ALERTMANAGER_URL", "http://localhost:9093"),
		PrometheusURL:    getEnvStr("PROMETHEUS_URL", "http://localhost:9090"),
		RAGEngineURL:     getEnvStr("RAG_ENGINE_URL", "http://localhost:8080"),
		WatcherLogPath:   getEnvStr("WATCHER_LOG_PATH", filepath.Join(root, "tests", "logs", "watcher_log.jsonl")),
		RepoRoot:         root,
		NamespaceFilters: strings.Fields(getEnvStr("WATCHER_NAMESPACE_FILTER", "workloads")),
	}
}

func getEnvStr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func getEnvInt64(key string, def int64) int64 {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return n
		}
	}
	return def
}

func getEnvSeconds(key string, defSeconds int64) time.Duration {
	return time.Duration(getEnvInt64(key, defSeconds)) * time.Second
}
