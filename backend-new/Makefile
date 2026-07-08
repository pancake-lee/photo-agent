GOHOSTOS:=$(shell go env GOHOSTOS)
GOPATH:=$(shell go env GOPATH)

# 取git commit的8位编号，支持通过 make -v VERSION=x.x.x 覆盖
VERSION?=$(shell git describe --tags --always --dirty)
COMMIT=$(shell git describe --tags --always --dirty)

dbIP?=127.0.0.1
dbPort?=3306
dbUser?=pgo
dbPass?=pgo
dbName?=pgo

dbCmd=mysql -h $(dbIP) -P ${dbPort} -u $(dbUser) -p$(dbPass)

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
	$(dbCmd) -e "DROP DATABASE IF EXISTS ${dbName}_orm; CREATE DATABASE ${dbName}_orm DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
	for file in ${dbSqlPath}/*.sql; do \
		$(dbCmd) ${dbName}_orm < $$file; \
	done

	rm -rf ${dbCodePath}/model/
	rm -rf ${dbCodePath}/query/
	
	
# 	最初用的是GORM的[gentool]，后来因为前后还要嵌入我自己的逻辑，
#   就集成到pgo里了，底层依然调用了gentool，make env 中安装了 pgo
	pgo genGORM \
		-db mysql \
		-dsn "${dbUser}:${dbPass}@tcp(${dbIP}:${dbPort})/${dbName}_orm?charset=utf8mb4&parseTime=True&loc=Local" \
		-outPath ${dbCodePath}/query/ \
		-outFile query.go \
		-modelPkgName model \

.PHONY: initDB
initDB:
	$(dbCmd) -e "CREATE DATABASE ${dbName} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
	for file in ./sql/*.sql; do \
		$(dbCmd) ${dbName} < $$file; \
	done

.PHONY: reInitDB
# 慎重，这是重置数据库的操作
reInitDB:
	$(dbCmd) -e "DROP DATABASE ${dbName};"
	make initDB

.PHONY: curd
# 根据数据库生成 CURD 代码
curd:
	pgo genCURD -db mysql -dsn "${dbUser}:${dbPass}@tcp(${dbIP}:${dbPort})/${dbName}_orm?charset=utf8mb4&parseTime=True&loc=Local"

.PHONY: build
# build
build: 
	go build -ldflags "-X main.version=$(VERSION) -X main.commit=$(git rev-parse HEAD) -X main.date=$(date +%Y-%m-%dT%H:%M:%S)" -o ./bin/ ./...

.PHONY: precommit
# 提交生成的代码[*.pb.go, ./cmd/pgo/swagger/*, *.gen.go, *.gen.proto]
precommit:
	git add "openapi.yaml"
	git add "*.pb.go"
	git add "./cmd/pgo/swagger/*"
	git add "*.gen.go"
	git add "*.gen.proto"
	git add "./internal/pkg/db/model/"
	git add "./internal/pkg/db/query/"
	git commit -m "gen: update generated code"

# --------------------------------------------------
.PHONY: api-cli
# generate cli sdk from openapi.yaml
api-cli:

# openapitools/openapi-generator-cli不管是docker还是jar包，都有一个问题：
# proto通过gnostic生成的openapi.yaml不带required标识，所有字段都是可选
# 这导致生成go客户端代码时，所有字段都是指针类型，使用起来非常麻烦
# docker run --rm -v ./:/local openapitools/openapi-generator-cli:v7.18.0 generate -i /local/openapi.yaml -g go -o /local/client/swagger -p packageName=swagger

# dnf install -y java-11-openjdk-headless
# wget https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/7.19.0/openapi-generator-cli-7.19.0.jar
# java -jar ~/openapi-generator-cli-7.19.0.jar generate \
# 	-i ./openapi.yaml \
# 	-g go \
# 	-o ./cmd/pgo/swagger \
# 	-p packageName=swagger \
# 	-p withGoMod=false \

# swagger家的没问题，不是指针
# wget https://repo1.maven.org/maven2/io/swagger/codegen/v3/swagger-codegen-cli/3.0.77/swagger-codegen-cli-3.0.77.jar -O swagger-codegen-cli.jar
	java -jar ~/swagger-codegen-cli.jar generate \
		-i ./openapi.yaml \
		-l go \
		-o ./cmd/pgo/swagger \
		-D packageName=swagger \
	
	rm -f client/swagger/go.mod
	rm -f client/swagger/go.sum

.PHONY: cli
# build pgo for current platform
cli:
	go build -ldflags "-X main.version=$(VERSION) -X main.commit=$(COMMIT) -X main.date=$(shell date +%Y-%m-%dT%H:%M:%S)" -o ./bin/pgo ./cmd/pgo

.PHONY: cli-win
# build pgo for windows
cli-win:
	CC=x86_64-w64-mingw32-gcc CGO_ENABLED=1 GOOS=windows go build -ldflags "-H=windowsgui -X main.version=$(VERSION) -X main.commit=$(COMMIT) -X main.date=$(shell date +%Y-%m-%dT%H:%M:%S)" -o ./bin/pgo.exe ./cmd/pgo
