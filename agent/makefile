.PHONY: dev venv

# 显式重建 venv（项目迁移、环境损坏时使用）
venv:
	rm -rf .venv
	uv venv --python 3.12
	uv sync
	uv pip install pip
	uv pip install -e .
	@echo "✅ .venv 重建完成，执行 source .venv/bin/activate 启用"

# 隐式依赖：make dev 时若 .venv 不存在则自动创建
.venv:
	uv venv --python 3.12
	uv sync
	uv pip install pip
	uv pip install -e .

dev: .venv
	source .venv/bin/activate && python3 cli/photo_agent.py -c ../.local/my-config.yaml --serve -l
