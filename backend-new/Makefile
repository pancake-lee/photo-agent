GOHOSTOS:=$(shell go env GOHOSTOS)
GOPATH:=$(shell go env GOPATH)

# 取git commit的8位编号，支持通过 make -v VERSION=x.x.x 覆盖
VERSION?=$(shell git describe --tags --always --dirty)
COMMIT=$(shell git describe --tags --always --dirty)

# SQLite3 配置
DB_ORM_PATH?=./data/sqlite/photo_agent_orm.db

# 遍历所有proto文件
# every developer has a Git. run in GitBash.
API_PROTO_FILES=$(shell find ./proto -name *.proto)

# --------------------------------------------------
.PHONY: all
# generate all
all: gorm curd build

# show help
help:
	@echo ''
	@echo 'Usage:'
	@echo ' make [target]'
	@echo ''
	@echo 'Targets:'
	@awk '/^[a-zA-Z\-_0-9]+:/ { \
	helpMessage = match(lastLine, /^# (.*)/); \
		if (helpMessage) { \
			helpCommand = substr($$1, 0, index($$1, ":")); \
			helpMessage = substr(lastLine, RSTART + 2, RLENGTH); \
			printf "\033[36m%-10s\033[0m %s\n", helpCommand,helpMessage; \
		} \
	} \
	{ lastLine = $$0 }' $(MAKEFILE_LIST)

# 设置help为默认目标，平时默认目标是第一个目标
.DEFAULT_GOAL := help

# --------------------------------------------------
.PHONY: env
# 安装依赖
env:
# wget https://github.com/protocolbuffers/protobuf/releases/download/v28.1/protoc-28.1-linux-x86_64.zip
# unzip protoc-28.1-linux-x86_64.zip -d /usr/local
# rm -f rm protoc-28.1-linux-x86_64.zip
# go env -w GOPROXY=https://goproxy.cn,direct
# git config core.autocrlf false
# git config core.eol lf
	go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
	go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
	go install github.com/go-kratos/kratos/cmd/kratos/v2@latest
	go install github.com/go-kratos/kratos/cmd/protoc-gen-go-http/v2@latest
	go install github.com/google/gnostic/cmd/protoc-gen-openapi@latest
	go install github.com/go-kratos/kratos/cmd/protoc-gen-go-errors/v2@latest
	go install gorm.io/gen/tools/gentool@latest
	go install github.com/pancake-lee/pgo/cmd/pgo

# 跨平台编译cli-win时需要
	dnf install -y libX11-devel mesa-libGL-devel libXcursor-devel libXrandr-devel libXinerama-devel libXi-devel libXxf86vm-devel
	dnf install -y mingw64-gcc

	go mod tidy

# 安装自己
# go install ./cmd/pgo

.PHONY: api
# generate api proto
api:
	rm -f ./internal/pkg/api/*.pb.go
	protoc --proto_path=./proto/ \
		--proto_path=./third_party \
		--go_out=paths=source_relative:./internal/pkg/api/ \
		--go-http_out=paths=source_relative:./internal/pkg/api/ \
		--go-grpc_out=paths=source_relative:./internal/pkg/api/ \
		--go-errors_out=paths=source_relative:./internal/pkg/api/ \
		--openapi_out=fq_schema_naming=true,default_response=false:. \
		$(API_PROTO_FILES) \

	echo "servers:" >> ./openapi.yaml
	echo "    - description: PGO API" >> ./openapi.yaml
	echo "      url: http://127.0.0.1:8080" >> ./openapi.yaml

dbSqlPath?=./sql
dbCodePath?=./internal/pkg/db
.PHONY: gorm
gorm:
	rm -rf ${dbCodePath}/model/
	rm -rf ${dbCodePath}/query/

# 	最初用的是GORM的[gentool]，后来因为前后还要嵌入我自己的逻辑，
#   就集成到pgo里了，底层依然调用了gentool，make env 中安装了 pgo
	pgo genGORM \
		-db sqlite3 \
		-dsn "$(DB_ORM_PATH)" \
		-outPath ${dbCodePath}/query/ \
		-outFile query.go \
		-modelPkgName model \

.PHONY: initDB
# 创建 SQLite ORM 数据库并执行 DDL（genGORM / genCURD 的前置步骤）
initDB:
	@mkdir -p ./data/sqlite
	rm -f $(DB_ORM_PATH)
	for file in ${dbSqlPath}/*.sql; do \
		echo "executing $$file ..."; \
		sqlite3 $(DB_ORM_PATH) < $$file; \
	done
	@echo "ORM database created: $(DB_ORM_PATH)"

.PHONY: curd
# 根据数据库生成 CURD 代码
curd:
	pgo genCURD -db sqlite3 -dsn "$(DB_ORM_PATH)"

.PHONY: build
# build
build: 
	go build -ldflags "-X main.version=$(VERSION) -X main.commit=$(git rev-parse HEAD) -X main.date=$(date +%Y-%m-%dT%H:%M:%S)" -o ./bin/ ./...

.PHONY: precommit
# 提交生成的代码[*.pb.go, ./cmd/pgo/swagger/*, *.gen.go, *.gen.proto]
# 该命令执行后，剩下的就是手动修改的代码，方便分开审查，也方便分开提交
precommit:
	git add "openapi.yaml"
	git add "*.pb.go"
	git add "*.gen.go"
	git add "*.gen.proto"
	git add "./internal/pkg/db/model/"
	git add "./internal/pkg/db/query/"
	git commit -m "gen: update generated code"

# --------------------------------------------------
.PHONY: api-cli
# generate cli sdk from openapi.yaml
api-cli:
# dnf install java
# wget https://repo1.maven.org/maven2/io/swagger/codegen/v3/swagger-codegen-cli/3.0.77/swagger-codegen-cli-3.0.77.jar -O swagger-codegen-cli.jar
	java -jar ~/swagger-codegen-cli.jar generate \
		-i ./openapi.yaml \
		-l python \
		-o ../agent/backend-sdk \

	java -jar ~/swagger-codegen-cli.jar generate \
		-i ./openapi.yaml \
		-l typescript-fetch \
		-o ../web/backend-sdk \
	

