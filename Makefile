# Thin wrapper: the real logic is in scripts/*.sh, so `bash scripts/<name>.sh` works without make.
SHELL := bash
.DEFAULT_GOAL := help
export PORT ?= 3000

.PHONY: help setup doctor demo demo-stop demo-status test test-fast eval g1-eval serve clean

help: ## Show this list
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-12s %s\n", $$1, $$2}'
	@echo ""
	@echo "  Options: PORT=3100 make demo   (web app port, default 3000)   OPEN=0 make demo   (do not open a browser)"

setup: ## Check tools, install dependencies, build the UI and the sherlock binary (run once)
	@bash scripts/setup.sh

doctor: ## Check tools, versions and free ports; prints a fix for each problem
	@bash scripts/doctor.sh

demo: ## Start the demo (teams + recorded runs + web app) and open it in the browser
	@bash scripts/demo.sh

demo-stop: ## Stop the demo servers
	@bash scripts/demo-stop.sh

demo-status: ## Show whether the demo is running
	@bash scripts/demo.sh status

test: ## Full pre-deploy gate (about 10 minutes, includes the 5-minute evaluation)
	@bash scripts/test.sh

test-fast: ## Quick checks: no evaluation, no live servers (a few minutes)
	@bash scripts/test-fast.sh

eval: ## Regenerate the evaluation tables in docs/eval (about 5 minutes)
	cd python/sherlock && uv run python eval/run_eval.py --out ../../docs/eval

g1-eval: ## G1 Laya evaluation and ship decision (needs LAYA_API_KEY with credits, ~$0.12, ~30 minutes)
	@bash scripts/g1-eval.sh

serve: ## Dev server against your own `langgraph dev` on :2024 (port $(PORT))
	cargo run -p cli -- serve --port $(PORT)

clean: demo-stop ## Stop the demo and delete .sherlock-demo/
	rm -rf .sherlock-demo
