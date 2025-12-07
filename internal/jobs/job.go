package jobs

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"sync"
	"time"
)

type Status string

const (
	StatusPending  Status = "pending"
	StatusRunning  Status = "running"
	StatusFinished Status = "finished"
	StatusError    Status = "error"
)

type Job struct {
	ID     string      `json:"id"`
	Status Status      `json:"status"`
	Result interface{} `json:"result"`
	Error  string      `json:"error"`
	Hops   int         `json:"hops"`

	// Add fields so CreateJob is valid:
	Start  string `json:"start"`
	Target string `json:"target"`
}

type JobManager struct {
	mu   sync.RWMutex
	jobs map[string]*Job
}

func NewJobManager() *JobManager {
	return &JobManager{
		jobs: make(map[string]*Job),
	}
}

func (jm *JobManager) CreateJob() *Job {
	jm.mu.Lock()
	defer jm.mu.Unlock()

	id := RandID()
	job := &Job{ID: id, Status: StatusPending}
	jm.jobs[id] = job
	return job
}

func (jm *JobManager) Update(id string, fn func(*Job)) {
	jm.mu.Lock()
	defer jm.mu.Unlock()
	if j, ok := jm.jobs[id]; ok {
		fn(j)
	}
}

func (jm *JobManager) Get(id string) (*Job, bool) {
	jm.mu.RLock()
	defer jm.mu.RUnlock()
	j, ok := jm.jobs[id]
	return j, ok
}

// RandID returns a random 16-byte hex string as a unique job ID.
func RandID() string {
	b := make([]byte, 16)
	_, err := rand.Read(b)
	if err != nil {
		return fmt.Sprintf("job_%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(b)
}
