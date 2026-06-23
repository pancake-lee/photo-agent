.PHONY: all backend dev clean

BIN_DIR := ../bin

all: backend

backend:
	@mkdir -p $(BIN_DIR)
	go build -ldflags "-s -w" -o $(BIN_DIR)/server ./cmd/server
	go build -ldflags "-s -w" -o $(BIN_DIR)/batch_vlm ./cmd/batch_vlm
	go build -ldflags "-s -w" -o $(BIN_DIR)/backendTest ./test/backendTest.go
	go build -ldflags "-s -w" -o $(BIN_DIR)/init_dify ./cmd/init_dify

dev:
	go run ./cmd/server -c ../.local/pancake.yaml -l

clean:
	rm -rf $(BIN_DIR)
