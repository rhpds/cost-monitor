#!/bin/bash
# Development utility script for Cost Monitor project
# Provides convenient developer commands for quality assurance

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Print colored output
print_header() {
    echo -e "${CYAN}🚀 $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

show_help() {
    echo -e "${CYAN}Cost Monitor - Development Commands${NC}"
    echo "=================================="
    echo ""
    echo "Usage: ./scripts/dev.sh <command>"
    echo ""
    echo "Available commands:"
    echo "  install      Install development dependencies and setup pre-commit hooks"
    echo "  format       Format code with Black and sort imports with isort"
    echo "  lint         Run comprehensive linting with Ruff and type checking with MyPy"
    echo "  test         Run pytest with coverage"
    echo "  test-fast    Run tests without coverage for speed"
    echo "  test-smoke   Run smoke tests (same as pre-commit)"
    echo "  test-all     Run complete integration test suite (71 tests)"
    echo "  quality      Run all quality checks (format, lint, dead-code, secrets)"
    echo "  dead-code    Detect dead code with Vulture"
    echo "  secrets      Scan for secrets and credentials"
    echo "  clean        Clean up temporary files and caches"
    echo "  dashboard    Start development dashboard server"
    echo "  api          Start development API server"
    echo "  help         Show this help message"
    echo ""
}

install_deps() {
    print_header "Installing development dependencies..."
    pip install -e .[dev,test]
    print_header "Installing pre-commit hooks..."
    pre-commit install
    pre-commit install --hook-type commit-msg
    if [ ! -f .secrets.baseline ]; then
        print_header "Creating secrets baseline..."
        detect-secrets scan --baseline .secrets.baseline
    fi
    print_success "Development environment setup complete"
}

format_code() {
    print_header "Formatting code with Black..."
    black src/ --config pyproject.toml
    print_header "Sorting imports with isort..."
    isort src/ --settings-path pyproject.toml
    print_success "Code formatting complete"
}

lint_code() {
    print_header "Running Ruff linter..."
    ruff check src/ --config pyproject.toml
    print_header "Running MyPy type checker..."
    mypy src/ --config-file pyproject.toml
    print_success "Linting complete"
}

run_tests() {
    print_header "Running tests with coverage..."
    pytest --cov=src --cov-report=term-missing --cov-report=html
    print_success "Tests complete"
}

run_tests_fast() {
    print_header "Running fast tests..."
    pytest -x --no-cov
    print_success "Fast tests complete"
}

run_smoke_tests() {
    print_header "Running smoke tests (same as pre-commit)..."
    pytest \
        tests/integration/test_api_endpoints.py::TestHealthEndpoints::test_health_live \
        tests/integration/test_api_endpoints.py::TestCostEndpoints::test_cost_summary_endpoint \
        tests/integration/test_end_to_end.py::TestCompleteWorkflows::test_full_cost_collection_and_retrieval \
        -v --tb=short --no-cov
    print_success "Smoke tests complete"
}

run_all_tests() {
    print_header "Running complete integration test suite (71 tests)..."
    pytest tests/integration/ -v --tb=short
    print_success "All integration tests complete"
}

check_dead_code() {
    print_header "Scanning for dead code with Vulture..."
    vulture src/ --config pyproject.toml
    print_success "Dead code scan complete"
}

scan_secrets() {
    print_header "Scanning for secrets with detect-secrets..."
    detect-secrets scan --baseline .secrets.baseline
    if command -v gitleaks >/dev/null 2>&1; then
        print_header "Scanning for secrets with gitleaks..."
        gitleaks detect --source . --verbose
    fi
    print_success "Secret scanning complete"
}

run_quality() {
    print_header "Running comprehensive quality checks..."
    format_code
    lint_code
    check_dead_code
    scan_secrets
    print_success "All quality checks passed!"
}

clean_cache() {
    print_header "Cleaning up temporary files and caches..."
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete
    find . -type f -name "*.pyo" -delete
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
    rm -rf htmlcov/ dist/ build/ *.egg-info/
    print_success "Cleanup complete"
}

start_dashboard() {
    print_header "Starting development dashboard..."
    python -m src.main dashboard
}

start_api() {
    print_header "Starting development API server..."
    uvicorn src.api.data_service:app --reload --host 0.0.0.0 --port 8000
}

# Main command dispatcher
case "${1:-help}" in
    install)
        install_deps
        ;;
    format)
        format_code
        ;;
    lint)
        lint_code
        ;;
    test)
        run_tests
        ;;
    test-fast)
        run_tests_fast
        ;;
    test-smoke)
        run_smoke_tests
        ;;
    test-all)
        run_all_tests
        ;;
    quality)
        run_quality
        ;;
    dead-code)
        check_dead_code
        ;;
    secrets)
        scan_secrets
        ;;
    clean)
        clean_cache
        ;;
    dashboard)
        start_dashboard
        ;;
    api)
        start_api
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        print_error "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
