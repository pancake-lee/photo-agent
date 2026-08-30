// Package testutil supplies the production-migration schema baseline to Go tests.
package testutil

import (
	_ "embed"
	"os"
	"path/filepath"
	"testing"

	appdb "backend/internal/pkg/db"

	"github.com/pancake-lee/pgo/pkg/pdb"
)

//go:embed testdata/photo_agent_schema.sqlite
var schemaBaseline []byte

// InitSchemaSQLite copies the versioned empty schema baseline to a test-local DB.
// Callers may run production migration afterwards only to assert schema compatibility.
func InitSchemaSQLite(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "photo-agent.db")
	if err := os.WriteFile(path, schemaBaseline, 0600); err != nil {
		t.Fatalf("copy schema baseline: %v", err)
	}
	if err := pdb.InitSqlite(path); err != nil {
		t.Fatalf("init baseline sqlite: %v", err)
	}
	return path
}

// AssertMigrationCompatible proves the copied baseline already matches the
// current production migration. A mismatch gives maintainers a direct refresh
// command instead of letting tests repair the schema themselves.
func AssertMigrationCompatible(t *testing.T) {
	t.Helper()
	before := schemaSignature(t)
	if err := appdb.Migrate(); err != nil {
		t.Fatalf("run production migration against schema baseline: %v", err)
	}
	after := schemaSignature(t)
	if before != after {
		t.Fatalf("schema baseline is stale; refresh it with `GOTOOLCHAIN=local go run ./cmd/schema-baseline`: before=%q after=%q", before, after)
	}
}

func schemaSignature(t *testing.T) string {
	t.Helper()
	var signature string
	if err := pdb.GetGormDB().Raw("SELECT group_concat(sql, '\n') FROM sqlite_master WHERE type = 'table' ORDER BY name").Scan(&signature).Error; err != nil {
		t.Fatalf("read schema signature: %v", err)
	}
	return signature
}
