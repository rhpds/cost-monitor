# Makefile for Cost Monitor project
# Provides convenient developer targets for quality assurance

.PHONY: help install format lint dead-code quality test clean docker-build docker-run

# Default target
help: ## Show this help message
	@echo "Cost Monitor - Development Commands"
	@echo "=================================="
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Quality targets can be combined: make format lint"
	@echo "Run 'make quality' for complete code quality check"

# Environment setup
install: ## Install development dependencies and setup pre-commit hooks
	@echo "Installing development dependencies..."
	pip install -e .[dev,test]
	@echo "Installing pre-commit hooks..."
	pre-commit install
	pre-commit install --hook-type commit-msg
	@echo "Creating secrets baseline..."
	@if [ ! -f .secrets.baseline ]; then \
		detect-secrets scan --baseline .secrets.baseline; \
	fi
	@echo "✅ Development environment setup complete"

install-minimal: ## Install only core dependencies (production)
	@echo "Installing core dependencies..."
	pip install -e .
	@echo "✅ Minimal installation complete"

# Code formatting
format: ## Format code with Black and sort imports with isort
	@echo "🔧 Formatting code with Black..."
	black src/ --config pyproject.toml
	@echo "🔧 Sorting imports with isort..."
	isort src/ --settings-path pyproject.toml
	@echo "✅ Code formatting complete"

format-check: ## Check if code formatting is correct without making changes
	@echo "🔍 Checking code formatting..."
	black src/ --check --config pyproject.toml
	isort src/ --check-only --settings-path pyproject.toml
	@echo "✅ Code formatting check complete"

# Linting
lint: ## Run comprehensive linting with Ruff and type checking with MyPy
	@echo "🔍 Running Ruff linter..."
	ruff check src/ --config pyproject.toml
	@echo "🔍 Running MyPy type checker..."
	mypy src/ --config-file pyproject.toml
	@echo "✅ Linting complete"

lint-fix: ## Run linting with automatic fixes
	@echo "🔧 Running Ruff with auto-fix..."
	ruff check src/ --config pyproject.toml --fix
	@echo "✅ Linting with fixes complete"

# Dead code detection
dead-code: ## Detect dead code with Vulture
	@echo "🔍 Scanning for dead code with Vulture..."
	vulture src/ --config pyproject.toml
	@echo "✅ Dead code scan complete"

# Secret scanning
secrets-scan: ## Scan for secrets and credentials
	@echo "🔍 Scanning for secrets with detect-secrets..."
	detect-secrets scan --baseline .secrets.baseline
	@echo "🔍 Scanning for secrets with gitleaks..."
	gitleaks detect --source . --verbose
	@echo "✅ Secret scanning complete"

secrets-update: ## Update secrets baseline with new findings
	@echo "🔧 Updating secrets baseline..."
	detect-secrets scan --baseline .secrets.baseline --update
	@echo "✅ Secrets baseline updated"

# Comprehensive quality check
quality: format-check lint dead-code secrets-scan ## Run all quality checks (format, lint, dead-code, secrets)
	@echo "🎉 All quality checks passed!"

quality-fix: format lint-fix ## Run all quality tools with auto-fixes
	@echo "🎉 Code quality improved with auto-fixes!"

# Testing
test: ## Run pytest with coverage
	@echo "🧪 Running tests with coverage..."
	pytest --cov=src --cov-report=term-missing --cov-report=html
	@echo "✅ Tests complete"

test-fast: ## Run tests without coverage for speed
	@echo "🧪 Running fast tests..."
	pytest -x --no-cov
	@echo "✅ Fast tests complete"

test-watch: ## Run tests in watch mode (requires pytest-watch)
	@echo "🧪 Running tests in watch mode..."
	ptw -- --no-cov

# Pre-commit hooks
pre-commit: ## Run pre-commit hooks on all files
	@echo "🔧 Running pre-commit hooks on all files..."
	pre-commit run --all-files
	@echo "✅ Pre-commit hooks complete"

pre-commit-update: ## Update pre-commit hook versions
	@echo "🔧 Updating pre-commit hooks..."
	pre-commit autoupdate
	@echo "✅ Pre-commit hooks updated"

# Development server
dev-dashboard: ## Start development dashboard server
	@echo "🚀 Starting development dashboard..."
	python -m src.main dashboard

dev-api: ## Start development API server
	@echo "🚀 Starting development API server..."
	uvicorn src.api.data_service:app --reload --host 0.0.0.0 --port 8000

# Docker operations
docker-build: ## Build Docker image
	@echo "🐳 Building Docker image..."
	docker build -t cost-monitor:latest .
	@echo "✅ Docker image built"

docker-run: ## Run Docker container
	@echo "🐳 Running Docker container..."
	docker run --rm -it -p 8080:8080 -p 8000:8000 cost-monitor:latest

docker-compose-up: ## Start services with docker-compose
	@echo "🐳 Starting services with docker-compose..."
	docker-compose up -d

docker-compose-down: ## Stop docker-compose services
	@echo "🐳 Stopping docker-compose services..."
	docker-compose down

# Cleanup
clean: ## Clean up temporary files and caches
	@echo "🧹 Cleaning up..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info/
	@echo "✅ Cleanup complete"

# Deployment helpers
deploy-check: ## Check deployment configuration
	@echo "🔍 Checking deployment configuration..."
	./scripts/quality-check.sh
	@echo "✅ Deployment check complete"

# OpenShift/Kubernetes
oc-deploy: ## Deploy to OpenShift using local configuration
	@echo "🚀 Deploying to OpenShift..."
	./deploy.sh
	@echo "✅ OpenShift deployment complete"

# Documentation
docs-serve: ## Serve documentation locally (if using MkDocs)
	@if [ -f "mkdocs.yml" ]; then \
		echo "📚 Serving documentation..."; \
		mkdocs serve; \
	else \
		echo "❌ No MkDocs configuration found"; \
	fi

# Git helpers
git-hooks-test: ## Test git hooks without committing
	@echo "🔧 Testing git hooks..."
	pre-commit run --all-files --hook-stage manual
	@echo "✅ Git hooks test complete"

# Performance profiling (optional)
profile: ## Profile application performance (requires py-spy)
	@echo "📊 Profiling application performance..."
	@if command -v py-spy >/dev/null 2>&1; then \
		echo "Use: py-spy record -o profile.svg -- python -m src.main dashboard"; \
	else \
		echo "Install py-spy for profiling: pip install py-spy"; \
	fi

# Security audit
audit: ## Run security audit with safety and bandit
	@echo "🛡️ Running security audit..."
	@if command -v safety >/dev/null 2>&1; then \
		safety check; \
	else \
		echo "Install safety for dependency audit: pip install safety"; \
	fi
	@if command -v bandit >/dev/null 2>&1; then \
		bandit -r src/ -f json -o bandit-report.json; \
		echo "Bandit report saved to bandit-report.json"; \
	else \
		echo "Install bandit for security scanning: pip install bandit"; \
	fi

# Show project status
status: ## Show project status and tool versions
	@echo "Cost Monitor - Project Status"
	@echo "============================="
	@echo "Python version: $(shell python --version 2>&1)"
	@echo "Pre-commit version: $(shell pre-commit --version 2>/dev/null || echo 'Not installed')"
	@echo "Git status:"
	@git status --porcelain | head -10 || echo "Not a git repository"
	@echo ""
	@echo "Recent commits:"
	@git log --oneline -5 2>/dev/null || echo "No git history"
	@echo ""
	@echo "Environment variables:"
	@echo "  DATABASE_URL: $(shell echo $${DATABASE_URL:-'Not set'})"
	@echo "  REDIS_URL: $(shell echo $${REDIS_URL:-'Not set'})"
