.PHONY: start stop status

PID_DIR := .pids
LOG_DIR := logs

# 各服务端口（用于兜底清理）
BACKEND_PORT := 10004
AGENT_PORT   := 10005
WEB_PORT     := 10006

# ── 启动全部服务 ──────────────────────────────────────────
start:
	# 确保所有服务已停止
	make stop
	sleep 1

	@mkdir -p $(PID_DIR)
	@mkdir -p $(LOG_DIR)
	@echo "🚀 启动全部服务..."

	@# Backend (Go) — setsid 创建独立进程组，确保 stop 能整组杀死
	@setsid sh -c 'cd backend && make dev' \
		> $(LOG_DIR)/backend.log 2>&1 & echo $$! > $(PID_DIR)/backend.pid
	@echo "  ✓ backend  (pgid $$(cat $(PID_DIR)/backend.pid))"

	@# Agent (Python)
	@setsid sh -c 'cd agent && make dev' \
		> $(LOG_DIR)/agent.log 2>&1 & echo $$! > $(PID_DIR)/agent.pid
	@echo "  ✓ agent    (pgid $$(cat $(PID_DIR)/agent.pid))"

	@# Web (Vite)
	@setsid sh -c 'cd web && pnpm dev' \
		> $(LOG_DIR)/web.log 2>&1 & echo $$! > $(PID_DIR)/web.pid
	@echo "  ✓ web      (pgid $$(cat $(PID_DIR)/web.pid))"

	@echo "📋 日志目录: $(LOG_DIR)/"
	@echo "   停止服务: make stop"

# ── 停止全部服务 ──────────────────────────────────────────
stop:
	@echo "🛑 停止全部服务..."

	@# 第一步：按 PID 文件杀死进程组（PGID = PID，setsid 保证一致）
	@for name in backend agent web; do \
		pid_file="$(PID_DIR)/$$name.pid"; \
		if [ -f "$$pid_file" ]; then \
			pgid=$$(cat "$$pid_file"); \
			if kill -0 $$pgid 2>/dev/null; then \
				echo "  ✕ $$name (pgid $$pgid)"; \
				kill -- -$$pgid 2>/dev/null || true; \
			else \
				echo "  - $$name (pgid $$pgid 已退出)"; \
			fi; \
			rm -f "$$pid_file"; \
		fi; \
	done
	@sleep 0.5
	@# 第二步：强杀仍在 PID 文件中的残留
	@for name in backend agent web; do \
		pid_file="$(PID_DIR)/$$name.pid"; \
		if [ -f "$$pid_file" ]; then \
			pgid=$$(cat "$$pid_file"); \
			kill -9 -- -$$pgid 2>/dev/null || true; \
			rm -f "$$pid_file"; \
		fi; \
	done
	@# 第三步：端口兜底清理 — 杀死占用已知端口的所有进程（处理 PID 文件丢失 / 孤儿进程）
	@for port in $(BACKEND_PORT) $(AGENT_PORT) $(WEB_PORT); do \
		fuser -k -TERM $$port/tcp 2>/dev/null || true; \
	done
	@sleep 0.3
	@for port in $(BACKEND_PORT) $(AGENT_PORT) $(WEB_PORT); do \
		fuser -k -KILL $$port/tcp 2>/dev/null || true; \
	done
	@rm -rf $(PID_DIR)
	@echo "✅ 全部已停止"

# ── 查看服务状态 ──────────────────────────────────────────
status:
	@echo "📊 服务状态:"
	@for name in backend agent web; do \
		pid_file="$(PID_DIR)/$$name.pid"; \
		if [ -f "$$pid_file" ]; then \
			pid=$$(cat "$$pid_file"); \
			if kill -0 $$pid 2>/dev/null; then \
				echo "  ● $$name (pgid $$pid) ✓"; \
			else \
				echo "  ○ $$name (pid 文件存在但进程组已退出)"; \
			fi; \
		else \
			echo "  ○ $$name (未启动)"; \
		fi; \
	done
	@# 端口占用提示
	@echo ""
	@echo "📡 端口占用:"
	@ss -tlnp | grep -E "($(BACKEND_PORT)|$(AGENT_PORT)|$(WEB_PORT))" \
		| awk '{print "  " $$4 " → " $$NF}' || echo "  (无)"
