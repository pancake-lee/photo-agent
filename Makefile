.PHONY: all backend backend-test clean

BIN_DIR := bin

all: backend

backend:
	@mkdir -p $(BIN_DIR)
	cd backend && go build -ldflags "-s -w" -o ../$(BIN_DIR)/server ./cmd/server
	cd backend && go build -ldflags "-s -w" -o ../$(BIN_DIR)/batch_vlm ./cmd/batch_vlm

backend-test: backend
	@mkdir -p $(BIN_DIR)
	cd backend && go build -ldflags "-s -w" -o ../$(BIN_DIR)/backendTest ./test/backendTest.go

clean:
	rm -rf $(BIN_DIR)
