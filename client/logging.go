package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"os"
	"path/filepath"
	"runtime"
	"runtime/debug"
	"time"
)

type importTraceKey struct{}

type importTraceSpan struct {
	Count int     `json:"count"`
	MS    float64 `json:"ms"`
	MaxMS float64 `json:"max_ms"`
	Bytes int64   `json:"bytes,omitempty"`
}

type importTrace struct {
	batchID string
	phase   string
	start   time.Time
	spans   map[string]importTraceSpan
}

func startImportTrace(batchID, phase string) *importTrace {
	trace := &importTrace{batchID: batchID, phase: phase, start: time.Now(),
		spans: make(map[string]importTraceSpan)}
	writeImportTrace(map[string]any{"batch_id": batchID, "phase": phase,
		"event": "begin", "started_at": trace.start.UTC()})
	return trace
}

func (t *importTrace) context(ctx context.Context) context.Context {
	return context.WithValue(ctx, importTraceKey{}, t)
}

func importTraceFrom(ctx context.Context) *importTrace {
	t, _ := ctx.Value(importTraceKey{}).(*importTrace)
	return t
}

func traceMillis(elapsed time.Duration) float64 {
	return float64(elapsed.Microseconds()) / 1000
}

func (t *importTrace) add(name string, start time.Time, bytes int64) {
	if t == nil {
		return
	}
	ms := traceMillis(time.Since(start))
	span := t.spans[name]
	span.Count++
	span.MS += ms
	span.MaxMS = max(span.MaxMS, ms)
	span.Bytes += bytes
	t.spans[name] = span
}

func (t *importTrace) save(root string, batch *ImportBatch) error {
	start := time.Now()
	err := saveImportBatch(root, batch)
	t.add("save_batch", start, 0)
	return err
}

func (t *importTrace) finish(err error, fields map[string]any) {
	if fields == nil {
		fields = make(map[string]any)
	}
	fields["batch_id"], fields["phase"] = t.batchID, t.phase
	fields["duration_ms"], fields["spans"] = traceMillis(time.Since(t.start)), t.spans
	fields["event"], fields["started_at"] = "summary", t.start.UTC()
	fields["outcome"] = importTraceOutcome(err)
	if failed, _ := fields["failed"].(int); err == nil && failed > 0 {
		fields["outcome"] = "partial"
		if files, _ := fields["files"].(int); failed == files {
			fields["outcome"] = "error"
		}
	}
	writeImportTrace(fields)
}

func importTraceOutcome(err error) string {
	switch {
	case err == nil:
		return "ok"
	case errors.Is(err, context.Canceled):
		return "canceled"
	case errors.Is(err, context.DeadlineExceeded):
		return "timeout"
	default:
		return "error"
	}
}

func writeImportTrace(fields map[string]any) {
	fields["side"] = "client"
	raw, err := json.Marshal(fields)
	if err == nil {
		log.Printf("import.trace %s", raw)
	}
}

// setupLogging 将日志与标准错误输出重定向到文件，便于收集崩溃信息。
// 必须在 main 最早阶段调用，确保启动期崩溃也能被捕获。
func setupLogging() {
	// 崩溃 / panic 时打印全部 goroutine 堆栈
	debug.SetTraceback("all")

	dir := configDir()
	_ = os.MkdirAll(dir, 0o755)

	f, err := os.OpenFile(filepath.Join(dir, "photo-agent.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return
	}

	log.SetOutput(f)
	log.SetFlags(log.LstdFlags | log.Lmicroseconds | log.Lshortfile)

	// 让 Go 代码层的 stdout / stderr 也写入日志
	os.Stdout = f
	os.Stderr = f
	// 重定向底层句柄，捕获 runtime 的致命错误（panic / 访问违例）
	redirectStdError(f)

	log.Printf("=== photo-agent 启动 === pid=%d go=%s", os.Getpid(), runtime.Version())
}
