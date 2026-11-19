package service

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"backend/internal/defaultService/conf"
	khttp "github.com/go-kratos/kratos/v2/transport/http"
)

func TestImportReviewPersistsMergesAndLocks(t *testing.T) {
	setupUserPathTest(t)
	router := khttp.NewServer()
	(&PhotoServer{}).Reg(nil, router)
	server := httptest.NewServer(router)
	defer server.Close()
	base := server.URL + "/api/v1/photo-import/"
	request := func(method, path string, body any, code int) importReviewManifest {
		t.Helper()
		resp := doJSONRequest(t, server.Client(), method, base+path, body)
		var result importReviewManifest
		readArchiveTestResponse(t, resp, code, &result)
		return result
	}
	input := importReviewManifest{BatchID: strings.Repeat("a", 32), Name: "活动", Activity: "202611-活动"}
	root := filepath.Join(conf.C.Storage.PhotoSrc, importStageDirectory, input.BatchID)
	err := os.MkdirAll(root, 0700)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		digest := strings.Repeat(fmt.Sprint(i+1), 64)
		err = os.WriteFile(filepath.Join(root, digest+".jpg"), []byte("isolated staged fixture"), 0600)
		if err != nil {
			t.Fatal(err)
		}
		input.Entries = append(input.Entries, importReviewEntry{ID: fmt.Sprint(i), Name: fmt.Sprintf("%d.jpg", i), SHA256: digest, Decision: "kept", Origin: "manual"})
	}
	result := request("POST", "review/publish", input, 200)
	if result.Revision != 1 || result.State != "review" {
		t.Fatalf("first publish: %#v", result)
	}
	edit := func(id, decision string) map[string]any {
		return map[string]any{"batch_id": input.BatchID, "changes": []importReviewChange{{id, decision}}}
	}
	request("POST", "review/edit", edit("0", "favorite"), 200)
	request("POST", "review/edit", edit("1", "discarded"), 200)
	// An old PC manifest cannot overwrite either phone decision.
	result = request("POST", "review/publish", input, 200)
	if result.Entries[0].Decision != "favorite" || result.Entries[1].Decision != "discarded" {
		t.Fatal("republish overwrote decisions")
	}
	result = request("POST", "review/edit", edit("0", "discarded"), 200)
	if result.Entries[0].Decision != "discarded" || result.Entries[1].Decision != "discarded" {
		t.Fatal("last submission did not win")
	}
	revision := result.Revision
	bad := map[string]any{"batch_id": input.BatchID, "changes": []importReviewChange{{"0", "favorite"}, {"missing", "kept"}}}
	request("POST", "review/edit", bad, http.StatusConflict)
	result = request("GET", "review?batch_id="+input.BatchID, nil, 200)
	if result.Revision != revision || result.Entries[0].Decision != "discarded" {
		t.Fatal("invalid patch partially applied")
	}
	// Recreate the HTTP server to exercise file persistence rather than memory state.
	secondRouter := khttp.NewServer()
	(&PhotoServer{}).Reg(nil, secondRouter)
	second := httptest.NewServer(secondRouter)
	defer second.Close()
	var restored importReviewManifest
	resp := doJSONRequest(t, second.Client(), "GET", second.URL+"/api/v1/photo-import/review?batch_id="+input.BatchID, nil)
	readArchiveTestResponse(t, resp, 200, &restored)
	if restored.Revision != revision {
		t.Fatal("new server lost persistent state")
	}
	result = request("POST", "review/edit", map[string]string{"batch_id": input.BatchID, "state": "locked"}, 200)
	if result.State != "locked" || result.Revision <= revision {
		t.Fatal("lock missing")
	}
	request("POST", "review/edit", edit("0", "kept"), http.StatusConflict)
	request("POST", "review/publish", input, http.StatusConflict)
	request("POST", "review/edit", map[string]string{"batch_id": input.BatchID, "state": "review"}, 200)
	request("POST", "review/edit", edit("0", "kept"), 200)
	resp = doJSONRequest(t, server.Client(), "GET", base+"review/list", nil)
	var list []map[string]any
	readArchiveTestResponse(t, resp, 200, &list)
	if len(list) != 1 || list[0]["count"] != float64(2) {
		t.Fatalf("list: %#v", list)
	}
	// Concurrent individual updates must retain both photos' changes.
	var wg sync.WaitGroup
	for i := range 2 {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			response := doJSONRequest(t, server.Client(), "POST", base+"review/edit", edit(fmt.Sprint(i), "favorite"))
			readArchiveTestResponse(t, response, 200, nil)
		}(i)
	}
	wg.Wait()
	result = request("GET", "review?batch_id="+input.BatchID, nil, 200)
	if result.Entries[0].Decision != "favorite" || result.Entries[1].Decision != "favorite" {
		t.Fatal("concurrent patch lost unrelated changes")
	}
	request("POST", "stage/cleanup", map[string]string{"batch_id": input.BatchID}, 200)
	request("GET", "review?batch_id="+input.BatchID, nil, 404)
	request("POST", "review/edit", edit("0", "kept"), http.StatusConflict)
	request("GET", "review?batch_id=../", nil, http.StatusConflict)
}
