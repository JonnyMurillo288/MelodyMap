package jobs

import (
	"sync"

	"github.com/google/uuid"
)

// ManagerStruct manages all jobs in-memory.
type ManagerStruct struct {
	mu   sync.RWMutex
	jobs map[string]*Job
}

// Manager is the global job manager used by the main package.
var Manager = &ManagerStruct{
	jobs: make(map[string]*Job),
}

// CreateJob allocates a new Job with a unique ID and stores it.
func (m *ManagerStruct) CreateJob(start, target string) *Job {
	j := &Job{
		ID:     uuid.NewString(),
		Status: StatusPending,
		Start:  start,
		Target: target,
	}

	m.mu.Lock()
	m.jobs[j.ID] = j
	m.mu.Unlock()

	return j
}

// Update atomically updates a job, if it exists.
func (m *ManagerStruct) Update(id string, fn func(*Job)) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if job, ok := m.jobs[id]; ok {
		fn(job)
	}
}

// Get returns a job by ID.
func (m *ManagerStruct) Get(id string) (*Job, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()

	job, ok := m.jobs[id]
	return job, ok
}
