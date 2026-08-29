// list_backend_eval_files 输出后端代码质量评估应人工审阅的文件清单。
//
// 在仓库根目录运行：
//
//	GOTOOLCHAIN=local go run ./tools/list_backend_eval_files.go
//
// 加 --self-check 可同时验证核心纳入/排除规则。
package main

import (
	"flag"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const (
	categoryGo     = "手写 Go"
	categoryProto  = "人工 Proto"
	categorySQL    = "人工 SQL"
	categoryConfig = "后端配置"
	categoryDocs   = "直接技术文档"
)

var categoryList = []string{
	categoryGo,
	categoryProto,
	categorySQL,
	categoryConfig,
	categoryDocs,
}

var explicitCategoryMap = map[string]string{
	"backend/Makefile":    categoryConfig,
	"backend/go.mod":      categoryConfig,
	"configs/config.yaml": categoryConfig,
	"docs/deploy.md":      categoryDocs,
	"docs/tech.md":        categoryDocs,
}

var excludedDirList = []string{
	"backend/internal/abandonCodeService",
	"backend/internal/pkg/api",
	"backend/internal/pkg/db/model",
	"backend/internal/pkg/db/query",
	"backend/third_party",
}

func main() {
	rootPath := flag.String("root", ".", "仓库根目录")
	selfCheck := flag.Bool("self-check", false, "验证核心纳入/排除规则")
	flag.Parse()

	if *selfCheck {
		if err := runSelfCheck(); err != nil {
			fmt.Fprintf(os.Stderr, "规则自检失败: %v\n", err)
			os.Exit(1)
		}
		fmt.Println("规则自检: PASS")
	}

	absRootPath, err := filepath.Abs(*rootPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "解析仓库根目录失败: %v\n", err)
		os.Exit(1)
	}

	categoryToFileList, err := collectEvalFiles(absRootPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "收集评估文件失败: %v\n", err)
		os.Exit(1)
	}

	printFileList(absRootPath, categoryToFileList)
}

func collectEvalFiles(rootPath string) (map[string][]string, error) {
	categoryToFileList := make(map[string][]string, len(categoryList))
	for _, category := range categoryList {
		categoryToFileList[category] = []string{}
	}

	err := filepath.WalkDir(rootPath, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}

		relPath, err := filepath.Rel(rootPath, path)
		if err != nil {
			return err
		}
		relPath = filepath.ToSlash(relPath)

		if entry.IsDir() {
			if relPath != "." && isExcludedDir(relPath) {
				return filepath.SkipDir
			}
			return nil
		}

		category, included := classifyEvalFile(relPath)
		if included {
			categoryToFileList[category] = append(categoryToFileList[category], relPath)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}

	for _, category := range categoryList {
		sort.Strings(categoryToFileList[category])
	}
	return categoryToFileList, nil
}

func classifyEvalFile(relPath string) (string, bool) {
	if category, ok := explicitCategoryMap[relPath]; ok {
		return category, true
	}
	if isExcludedDir(relPath) {
		return "", false
	}

	if strings.HasPrefix(relPath, "backend/") && strings.HasSuffix(relPath, ".go") {
		if strings.HasSuffix(relPath, ".pb.go") || strings.HasSuffix(relPath, ".gen.go") {
			return "", false
		}
		return categoryGo, true
	}
	if strings.HasPrefix(relPath, "backend/proto/") && strings.HasSuffix(relPath, ".proto") {
		if strings.HasSuffix(relPath, ".gen.proto") || filepath.Base(relPath) == "abandonCode.proto" {
			return "", false
		}
		return categoryProto, true
	}
	if strings.HasPrefix(relPath, "backend/sql/") && strings.HasSuffix(relPath, ".sql") {
		if filepath.Base(relPath) == "abandon_code.sql" {
			return "", false
		}
		return categorySQL, true
	}
	return "", false
}

func isExcludedDir(relPath string) bool {
	for _, excludedDir := range excludedDirList {
		if relPath == excludedDir || strings.HasPrefix(relPath, excludedDir+"/") {
			return true
		}
	}
	return false
}

func printFileList(rootPath string, categoryToFileList map[string][]string) {
	fmt.Println("后端代码质量评估范围")
	fmt.Printf("仓库根目录: %s\n", rootPath)
	fmt.Println("以下文件应参与人工评估，列表之外的文件不纳入本轮范围。")

	total := 0
	for _, category := range categoryList {
		fileList := categoryToFileList[category]
		total += len(fileList)
		fmt.Printf("\n%s（%d）\n", category, len(fileList))
		for _, file := range fileList {
			fmt.Printf("  - %s\n", file)
		}
	}
	fmt.Printf("\n合计：%d 个文件\n", total)
}

func runSelfCheck() error {
	testCaseList := []struct {
		path     string
		category string
		included bool
	}{
		{"backend/internal/defaultService/service/svc_photo.go", categoryGo, true},
		{"backend/internal/pkg/api/photo_service.pb.go", "", false},
		{"backend/internal/defaultService/service/z_svc_photo.gen.go", "", false},
		{"backend/internal/pkg/db/query/query.go", "", false},
		{"backend/internal/abandonCodeService/service/svc_AbandonCode.go", "", false},
		{"backend/proto/photo_service.proto", categoryProto, true},
		{"backend/proto/z_defaultService.gen.proto", "", false},
		{"backend/proto/abandonCode.proto", "", false},
		{"backend/sql/photos.sql", categorySQL, true},
		{"backend/sql/abandon_code.sql", "", false},
		{"backend/Makefile", categoryConfig, true},
		{"configs/config.yaml", categoryConfig, true},
		{"docs/tech.md", categoryDocs, true},
	}

	for _, testCase := range testCaseList {
		actualCategory, actualIncluded := classifyEvalFile(testCase.path)
		if actualIncluded != testCase.included || actualCategory != testCase.category {
			return fmt.Errorf("%s: got (%q, %t), want (%q, %t)", testCase.path, actualCategory, actualIncluded, testCase.category, testCase.included)
		}
	}
	return nil
}
