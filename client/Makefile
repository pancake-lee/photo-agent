.PHONY: build-windows clean

# ── Windows 交叉编译 ──────────────────────────────────
# 前端 dist 由根目录 makefile 负责拷贝到 frontend/dist/
build-windows:
	CGO_ENABLED=1 GOOS=windows GOARCH=amd64 CC=x86_64-w64-mingw32-gcc \
		GOTOOLCHAIN=local go build -tags desktop,production,devtools -ldflags "-H windowsgui" -o ../bin/photo-agent.exe .

# ── 清理 ──────────────────────────────────────────────
clean:
	rm -f ../bin/photo-agent.exe
