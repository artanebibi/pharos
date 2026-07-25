package dedup

import (
	"sync"
	"time"
)

type Tracker struct {
	mu    sync.Mutex
	seen  map[string]time.Time
	nowFn func() time.Time
}

func New(nowFn func() time.Time) *Tracker {
	return &Tracker{
		seen:  make(map[string]time.Time),
		nowFn: nowFn,
	}
}

func (t *Tracker) IsFresh(fp string, ttl time.Duration) bool {
	t.mu.Lock()
	defer t.mu.Unlock()

	seenAt, ok := t.seen[fp]
	if !ok {
		return false
	}
	return t.nowFn().Sub(seenAt) < ttl
}

func (t *Tracker) MarkSeen(fp string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.seen[fp] = t.nowFn()
}

func (t *Tracker) Prune(ttl time.Duration) {
	t.mu.Lock()
	defer t.mu.Unlock()

	now := t.nowFn()
	for fp, seenAt := range t.seen {
		if now.Sub(seenAt) >= ttl {
			delete(t.seen, fp)
		}
	}
}
