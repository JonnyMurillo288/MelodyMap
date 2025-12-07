package spotify

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestBackoffDurationMonotonic(t *testing.T) {
	var prev time.Duration
	for i := 0; i < 5; i++ {
		d := backoffDuration(i)
		// base floor grows exponentially; with jitter it should never go below previous
		if i > 0 && d < prev {
			t.Fatalf("backoff should be monotonic non-decreasing: prev=%v cur=%v", prev, d)
		}
		// lower bound check: base*2^i
		base := 500 * time.Millisecond
		floor := time.Duration(1<<uint(i)) * base
		if d < floor {
			t.Fatalf("backoff below expected floor for attempt %d: got %v want >= %v", i, d, floor)
		}
		// upper bound check: floor + <300ms jitter
		if d >= floor+(300*time.Millisecond) {
			t.Fatalf("backoff exceeds expected upper bound for attempt %d: got %v, max %v", i, d, floor+(300*time.Millisecond))
		}
		prev = d
	}
}

func TestRetryAfterDelayHeaderSeconds(t *testing.T) {
	resp := &http.Response{Header: make(http.Header)}
	resp.Header.Set("Retry-After", "2")
	d := retryAfterDelay(resp)
	if d != 2*time.Second {
		t.Fatalf("unexpected retry-after: got %v want %v", d, 2*time.Second)
	}
}

func TestIOReadAll_LimitsTo10MB(t *testing.T) {
	// create >10MB reader
	b := strings.Repeat("a", (10<<20)+(1<<20)) // 11MB
	buf, err := ioReadAll(strings.NewReader(b))
	if err != nil {
		t.Fatalf("ioReadAll returned error: %v", err)
	}
	if len(buf) != 10<<20 {
		t.Fatalf("ioReadAll should limit to 10MB, got %d bytes", len(buf))
	}
}

func TestDoRequest_SetsHeadersAndQuery(t *testing.T) {
	// Test server that validates incoming headers and query parameters
	var seenHeader, seenQuery bool
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/echo" {
			if r.Header.Get("X-Test") == "yes" {
				seenHeader = true
			}
			q := r.URL.Query()
			if q.Get("q") == "value" && q.Get("a") == "b" {
				seenQuery = true
			}
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte("ok"))
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer ts.Close()

	oldClient := httpClient
	httpClient = ts.Client()
	defer func() { httpClient = oldClient }()

	body, status, err := doRequest("GET", ts.URL+"/echo", map[string]string{"X-Test": "yes"}, map[string]string{"q": "value", "a": "b"})
	if err != nil {
		t.Fatalf("doRequest error: %v", err)
	}
	if status != http.StatusOK {
		t.Fatalf("unexpected status: %d", status)
	}
	if string(body) != "ok" || !seenHeader || !seenQuery {
		t.Fatalf("server did not observe expected header/query; seenHeader=%v seenQuery=%v body=%q", seenHeader, seenQuery, string(body))
	}
}

func TestFetchWithRetry_ServerErrorThenSuccess(t *testing.T) {
	var calls int
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if calls == 1 {
			w.WriteHeader(http.StatusInternalServerError)
			_, _ = w.Write([]byte("err"))
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	}))
	defer ts.Close()

	oldClient := httpClient
	httpClient = ts.Client()
	defer func() { httpClient = oldClient }()

	req, _ := http.NewRequest("GET", ts.URL, nil)
	b, status, err := fetchWithRetry(req, 3)
	if err != nil {
		t.Fatalf("fetchWithRetry error: %v", err)
	}
	if status != http.StatusOK || string(b) != "ok" {
		t.Fatalf("unexpected result: status=%d body=%q calls=%d", status, string(b), calls)
	}
	if calls < 2 {
		t.Fatalf("expected at least 2 calls due to retry, got %d", calls)
	}
}

func TestFetchWithRetry_TooManyRequestsHonorsRetryAfter(t *testing.T) {
	var calls int
	var retryObserved bool
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if calls == 1 {
			w.Header().Set("Retry-After", strconv.Itoa(0)) // zero to avoid sleeping in test
			w.WriteHeader(http.StatusTooManyRequests)
			_, _ = w.Write([]byte("rate"))
			return
		}
		retryObserved = true
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	}))
	defer ts.Close()

	oldClient := httpClient
	httpClient = ts.Client()
	defer func() { httpClient = oldClient }()

	req, _ := http.NewRequest("GET", ts.URL, nil)
	b, status, err := fetchWithRetry(req, 2)
	if err != nil {
		t.Fatalf("fetchWithRetry error: %v", err)
	}
	if status != http.StatusOK || string(b) != "ok" || !retryObserved {
		t.Fatalf("unexpected result: status=%d body=%q calls=%d retryObserved=%v", status, string(b), calls, retryObserved)
	}
}

func TestDoRequest_QueryEncoding(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.URL.Query().Get("x"); got != "1 2" { // space should be encoded then decoded back
			w.WriteHeader(http.StatusBadRequest)
			_, _ = w.Write([]byte("bad query"))
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	}))
	defer ts.Close()

	oldClient := httpClient
	httpClient = ts.Client()
	defer func() { httpClient = oldClient }()

	_, status, err := doRequest("GET", ts.URL, map[string]string{}, map[string]string{"x": "1 2"})
	if err != nil || status != http.StatusOK {
		t.Fatalf("doRequest unexpected result: status=%d err=%v", status, err)
	}
}

// Ensure ioReadAll returns exactly what the underlying reader yields up to the cap
func TestIOReadAll_ReturnsData(t *testing.T) {
	data := []byte("hello world")
	buf, err := ioReadAll(bytes.NewReader(data))
	if err != nil {
		t.Fatalf("ioReadAll error: %v", err)
	}
	if !bytes.Equal(buf, data) {
		t.Fatalf("ioReadAll mismatch: got %q want %q", string(buf), string(data))
	}
}
