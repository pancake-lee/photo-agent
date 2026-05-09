.PHONY: all backend clean

BIN_DIR := bin

all: backend

backend:
	@mkdir -p $(BIN_DIR)
	cd backend && go build -ldflags "-s -w" -o ../$(BIN_DIR)/server ./cmd/server
	cd backend && go build -ldflags "-s -w" -o ../$(BIN_DIR)/batch_vlm ./cmd/batch_vlm

clean:
	rm -rf $(BIN_DIR)
