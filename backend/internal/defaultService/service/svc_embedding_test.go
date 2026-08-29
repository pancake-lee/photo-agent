package service

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

func withEmbeddingHTTPClient(t *testing.T, client *http.Client) {
	t.Helper()
	previous := embeddingHTTPClient
	embeddingHTTPClient = client
	t.Cleanup(func() { embeddingHTTPClient = previous })
}

func TestGenerateEmbeddingResponsePreservesInputOrderAndUsage(t *testing.T) {
	var requestCount int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		index := atomic.AddInt32(&requestCount, 1)
		if r.URL.Path != "/embeddings/multimodal" {
			t.Fatalf("path = %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"embedding":[` + string(rune('0'+index)) + `]},"usage":{"prompt_tokens":2,"total_tokens":3}}`))
	}))
	defer server.Close()
	withEmbeddingHTTPClient(t, server.Client())

	response, err := generateEmbeddingResponse(context.Background(), embedConfig{BaseURL: server.URL}, "model-a", []string{"first", "second"})
	if err != nil {
		t.Fatalf("generateEmbeddingResponse failed: %v", err)
	}
	if len(response.Data) != 2 || response.Data[0].Index != 0 || response.Data[1].Index != 1 {
		t.Fatalf("data = %#v", response.Data)
	}
	if response.Data[0].Embedding[0] != 1 || response.Data[1].Embedding[0] != 2 {
		t.Fatalf("embedding order = %#v", response.Data)
	}
	if response.Usage.PromptTokens != 4 || response.Usage.TotalTokens != 6 {
		t.Fatalf("usage = %#v", response.Usage)
	}
}

func TestGenerateEmbeddingResponseStopsAfterFailure(t *testing.T) {
	var requestCount int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&requestCount, 1)
		w.WriteHeader(http.StatusBadGateway)
		_, _ = w.Write([]byte(`upstream unavailable`))
	}))
	defer server.Close()
	withEmbeddingHTTPClient(t, server.Client())

	_, err := generateEmbeddingResponse(context.Background(), embedConfig{BaseURL: server.URL}, "model-a", []string{"first", "second"})
	if err == nil {
		t.Fatal("expected failure")
	}
	if got := atomic.LoadInt32(&requestCount); got != 1 {
		t.Fatalf("request count = %d, want 1", got)
	}
}

func TestCallVolcengineEmbeddingHonorsCancellationAndDeadline(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(100 * time.Millisecond)
	}))
	defer server.Close()
	withEmbeddingHTTPClient(t, server.Client())

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancel()
	_, err := callVolcengineEmbedding(ctx, embedConfig{BaseURL: server.URL}, "model-a", "blocked")
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("error = %v, want deadline exceeded", err)
	}

	canceledCtx, canceled := context.WithCancel(context.Background())
	canceled()
	_, err = callVolcengineEmbedding(canceledCtx, embedConfig{BaseURL: server.URL}, "model-a", "cancelled")
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, want context canceled", err)
	}
}
