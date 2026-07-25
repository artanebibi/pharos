package dedup

import (
	"sync"
	"testing"
	"time"
)

func TestIsFresh_TTLExpiry(t *testing.T) {
	base := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	now := base
	var mu sync.Mutex
	clock := func() time.Time {
		mu.Lock()
		defer mu.Unlock()
		return now
	}
	setNow := func(t2 time.Time) {
		mu.Lock()
		now = t2
		mu.Unlock()
	}

	tr := New(clock)
	tr.MarkSeen("fp1")

	setNow(base.Add(10 * time.Minute))
	if !tr.IsFresh("fp1", 15*time.Minute) {
		t.Errorf("expected fp1 to be fresh at t=10min with ttl=15min")
	}

	setNow(base.Add(20 * time.Minute))
	if tr.IsFresh("fp1", 15*time.Minute) {
		t.Errorf("expected fp1 to be stale at t=20min with ttl=15min")
	}
}

func TestIsFresh_UnknownFingerprint(t *testing.T) {
	tr := New(time.Now)
	if tr.IsFresh("nope", time.Hour) {
		t.Errorf("expected unknown fingerprint to be not fresh")
	}
}

func TestPrune_RemovesExpiredEntries(t *testing.T) {
	base := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	now := base
	clock := func() time.Time { return now }

	tr := New(clock)
	tr.MarkSeen("old")
	now = base.Add(20 * time.Minute)
	tr.MarkSeen("new")

	tr.Prune(15 * time.Minute)

	if tr.IsFresh("old", time.Hour) {
		t.Errorf("expected 'old' to be pruned")
	}
	if !tr.IsFresh("new", time.Hour) {
		t.Errorf("expected 'new' to survive prune")
	}
}

func TestConcurrentAccess(t *testing.T) {
	tr := New(time.Now)
	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(2)
		go func(n int) {
			defer wg.Done()
			tr.MarkSeen("fp")
		}(i)
		go func(n int) {
			defer wg.Done()
			tr.IsFresh("fp", time.Minute)
		}(i)
	}
	wg.Wait()
}
