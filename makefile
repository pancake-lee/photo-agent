.PHONY: start stop status

PID_DIR := .pids
LOG_DIR := logs

# ── 启动全部服务 ──────────────────────────────────────────
start:
	# 确保所有服务已停止
	make stop

	@mkdir -p $(PID_DIR)
	@mkdir -p $(LOG_DIR)
	@echo "🚀 启动全部服务..."

	@# Backend (Go)
	@nohup sh -c 'cd backend && make dev' \
		> $(LOG_DIR)/backend.log 2>&1 & echo $$! > $(PID_DIR)/backend.pid
	@echo "  ✓ backend  (pid $$(cat $(PID_DIR)/backend.pid))"

	@# Agent (Python)
	@nohup sh -c 'cd agent && make dev' \
		> $(LOG_DIR)/agent.log 2>&1 & echo $$! > $(PID_DIR)/agent.pid
	@echo "  ✓ agent    (pid $$(cat $(PID_DIR)/agent.pid))"

	@# Web (Vite)
	@nohup sh -c 'cd web && pnpm dev' \
		> $(LOG_DIR)/web.log 2>&1 & echo $$! > $(PID_DIR)/web.pid
	@echo "  ✓ web      (pid $$(cat $(PID_DIR)/web.pid))"

	@echo "📋 日志目录: $(LOG_DIR)/"
	@echo "   停止服务: make stop"

# ── 停止全部服务 ──────────────────────────────────────────
stop:
	@echo "🛑 停止全部服务..."
	@for name in backend agent web; do \
		pid_file="$(PID_DIR)/$$name.pid"; \
		if [ -f "$$pid_file" ]; then \
			pid=$$(cat "$$pid_file"); \
			if kill -0 $$pid 2>/dev/null; then \
				echo "  ✕ $$name (pid $$pid)"; \
				kill $$pid 2>/dev/null || true; \
				sleep 0.3; \
				kill -9 $$pid 2>/dev/null || true; \
			else \
				echo "  - $$name (pid $$pid 已退出)"; \
			fi; \
			rm -f "$$pid_file"; \
		else \
			echo "  - $$name (未找到 pid 文件)"; \
		fi; \
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
				echo "  ● $$name (pid $$pid) ✓"; \
			else \
				echo "  ○ $$name (pid 文件存在但进程已退出)"; \
			fi; \
		else \
			echo "  ○ $$name (未启动)"; \
		fi; \
	done
