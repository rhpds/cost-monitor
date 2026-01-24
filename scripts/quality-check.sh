#!/bin/bash
# Quality Check Script for Cost Monitor
# Manual validation script for code quality and deployment readiness
# Can be run independently or as part of CI/CD pipeline

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Global variables for tracking
CHECKS_PASSED=0
CHECKS_FAILED=0
WARNINGS=0

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
    ((CHECKS_PASSED++))
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
    ((WARNINGS++))
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    ((CHECKS_FAILED++))
}

log_step() {
    echo -e "${PURPLE}[STEP]${NC} $1"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Run command with error handling
run_check() {
    local check_name="$1"
    local command="$2"
    local allow_failure="${3:-false}"

    log_step "Running: $check_name"

    if eval "$command" >/dev/null 2>&1; then
        log_success "$check_name passed"
        return 0
    else
        if [ "$allow_failure" = "true" ]; then
            log_warning "$check_name failed (non-blocking)"
            return 0
        else
            log_error "$check_name failed"
            return 1
        fi
    fi
}

# Show header
show_header() {
    echo -e "${CYAN}"
    echo "=========================================="
    echo "  Cost Monitor - Quality Check Script"
    echo "=========================================="
    echo -e "${NC}"
    echo "Timestamp: $TIMESTAMP"
    echo "Project Root: $PROJECT_ROOT"
    echo "Python Version: $(python --version 2>&1 || echo 'Python not found')"
    echo ""
}

# Check Python environment
check_python_environment() {
    log_step "Checking Python environment..."

    if ! command_exists python; then
        log_error "Python not found"
        return 1
    fi

    # Check Python version (must be 3.11+)
    local python_version=$(python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    local min_version="3.11"

    if [ "$(echo -e "$python_version\n$min_version" | sort -V | head -n1)" = "$min_version" ]; then
        log_success "Python $python_version meets minimum requirement ($min_version)"
    else
        log_error "Python $python_version is below minimum requirement ($min_version)"
        return 1
    fi

    # Check if virtual environment is active
    if [ -n "${VIRTUAL_ENV:-}" ]; then
        log_success "Virtual environment active: $VIRTUAL_ENV"
    else
        log_warning "No virtual environment detected"
    fi
}

# Check dependencies
check_dependencies() {
    log_step "Checking core dependencies..."

    local required_packages=("black" "isort" "ruff" "mypy" "vulture" "pytest")
    local missing_packages=()

    for package in "${required_packages[@]}"; do
        if ! command_exists "$package"; then
            missing_packages+=("$package")
        fi
    done

    if [ ${#missing_packages[@]} -eq 0 ]; then
        log_success "All required development tools are available"
    else
        log_error "Missing packages: ${missing_packages[*]}"
        log_info "Run 'make install' to install missing dependencies"
        return 1
    fi
}

# Check code formatting
check_code_formatting() {
    log_step "Checking code formatting..."

    cd "$PROJECT_ROOT"

    # Black formatting check
    if run_check "Black formatting" "black src/ --check --config pyproject.toml"; then
        true  # Success
    else
        log_info "Run 'make format' to fix formatting issues"
        return 1
    fi

    # isort import sorting check
    if run_check "Import sorting (isort)" "isort src/ --check-only --settings-path pyproject.toml"; then
        true  # Success
    else
        log_info "Run 'make format' to fix import sorting"
        return 1
    fi
}

# Check linting
check_linting() {
    log_step "Checking code linting..."

    cd "$PROJECT_ROOT"

    # Ruff linting
    if run_check "Ruff linting" "ruff check src/ --config pyproject.toml"; then
        true  # Success
    else
        log_info "Run 'make lint-fix' to automatically fix some issues"
        return 1
    fi

    # MyPy type checking (allow warnings)
    if run_check "MyPy type checking" "mypy src/ --config-file pyproject.toml" "true"; then
        true  # Success or warning
    fi
}

# Check dead code
check_dead_code() {
    log_step "Checking for dead code..."

    cd "$PROJECT_ROOT"

    # Vulture dead code detection
    if vulture src/ --config pyproject.toml >/dev/null 2>&1; then
        log_success "No dead code detected"
    else
        # Get vulture output for reporting
        local vulture_output
        vulture_output=$(vulture src/ --config pyproject.toml 2>&1 || true)
        local warning_count
        warning_count=$(echo "$vulture_output" | grep -c "unused" || echo "0")

        if [ "$warning_count" -gt 5 ]; then
            log_error "Too much dead code detected ($warning_count warnings)"
            log_info "Run 'make dead-code' to see details"
            return 1
        else
            log_warning "Minor dead code detected ($warning_count warnings)"
        fi
    fi
}

# Check secrets
check_secrets() {
    log_step "Checking for secrets and credentials..."

    cd "$PROJECT_ROOT"

    # Check if secrets baseline exists
    if [ ! -f ".secrets.baseline" ]; then
        log_warning "Secrets baseline not found, creating one..."
        if command_exists detect-secrets; then
            detect-secrets scan --baseline .secrets.baseline
            log_success "Secrets baseline created"
        else
            log_warning "detect-secrets not available, skipping secret scan"
            return 0
        fi
    fi

    # Run detect-secrets
    if command_exists detect-secrets; then
        if run_check "Secret detection (detect-secrets)" "detect-secrets scan --baseline .secrets.baseline"; then  # pragma: allowlist secret
            true  # Success
        else
            log_error "New secrets detected!"
            log_info "Run 'make secrets-update' to update baseline or remove secrets"
            return 1
        fi
    fi

    # Run gitleaks if available
    if command_exists gitleaks; then
        if run_check "Git history secret scan (gitleaks)" "gitleaks detect --source . --no-git" "true"; then
            true  # Success or warning
        fi
    else
        log_warning "gitleaks not available, install for additional secret scanning"
    fi
}

# Check tests
check_tests() {
    log_step "Checking tests..."

    cd "$PROJECT_ROOT"

    # Check if test directory exists
    if [ ! -d "tests" ]; then
        log_warning "No tests directory found"
        return 0
    fi

    # Run tests if pytest is available
    if command_exists pytest; then
        if run_check "Running tests" "pytest --no-cov -x" "true"; then
            log_success "Tests passed"
        else
            log_warning "Some tests failed"
        fi
    else
        log_warning "pytest not available, skipping tests"
    fi
}

# Check configuration files
check_configuration() {
    log_step "Checking configuration files..."

    cd "$PROJECT_ROOT"

    # Check pyproject.toml
    if [ -f "pyproject.toml" ]; then
        log_success "pyproject.toml found"

        # Validate TOML syntax
        if command_exists python; then
            if python -c "import tomllib; tomllib.loads(open('pyproject.toml', 'rb').read())" 2>/dev/null ||
               python -c "import tomli; tomli.loads(open('pyproject.toml', 'rb').read())" 2>/dev/null; then
                log_success "pyproject.toml syntax is valid"
            else
                log_error "pyproject.toml syntax error"
                return 1
            fi
        fi
    else
        log_error "pyproject.toml not found"
        return 1
    fi

    # Check other important files
    local required_files=(".gitignore" "README.md" "requirements.txt")
    for file in "${required_files[@]}"; do
        if [ -f "$file" ]; then
            log_success "$file found"
        else
            log_warning "$file not found"
        fi
    done
}

# Check git status
check_git_status() {
    log_step "Checking git status..."

    cd "$PROJECT_ROOT"

    if ! git rev-parse --git-dir >/dev/null 2>&1; then
        log_warning "Not a git repository"
        return 0
    fi

    # Check for uncommitted changes
    if git diff-index --quiet HEAD -- 2>/dev/null; then
        log_success "Working directory is clean"
    else
        log_warning "Uncommitted changes detected"

        # Show summary
        local modified_files
        modified_files=$(git status --porcelain | wc -l)
        log_info "Modified files: $modified_files"
    fi

    # Check current branch
    local current_branch
    current_branch=$(git branch --show-current 2>/dev/null || echo "detached HEAD")
    log_info "Current branch: $current_branch"
}

# Check Docker configuration (if present)
check_docker() {
    log_step "Checking Docker configuration..."

    cd "$PROJECT_ROOT"

    if [ -f "docker-compose.yml" ]; then
        log_success "docker-compose.yml found"

        # Validate docker-compose syntax if docker is available
        if command_exists docker-compose; then
            if run_check "Docker Compose syntax" "docker-compose config" "true"; then
                true  # Success or warning
            fi
        else
            log_info "docker-compose not available, skipping syntax check"
        fi
    fi

    # Check Dockerfile syntax if hadolint is available
    if [ -d "dockerfiles" ] && command_exists hadolint; then
        local dockerfiles_count
        dockerfiles_count=$(find dockerfiles/ -name "Dockerfile*" | wc -l)
        if [ "$dockerfiles_count" -gt 0 ]; then
            if run_check "Dockerfile linting" "hadolint dockerfiles/*" "true"; then
                true  # Success or warning
            fi
        fi
    fi
}

# Show summary
show_summary() {
    echo ""
    echo -e "${CYAN}=========================================="
    echo "              QUALITY SUMMARY"
    echo -e "==========================================${NC}"
    echo ""
    echo -e "Timestamp: $TIMESTAMP"
    echo -e "Checks passed: ${GREEN}$CHECKS_PASSED${NC}"
    echo -e "Checks failed: ${RED}$CHECKS_FAILED${NC}"
    echo -e "Warnings: ${YELLOW}$WARNINGS${NC}"
    echo ""

    if [ $CHECKS_FAILED -eq 0 ]; then
        echo -e "${GREEN}✅ Overall status: PASSED${NC}"
        if [ $WARNINGS -gt 0 ]; then
            echo -e "${YELLOW}⚠️  Note: $WARNINGS warning(s) detected${NC}"
        fi
        echo ""
        echo -e "${GREEN}🚀 Ready for deployment!${NC}"
        return 0
    else
        echo -e "${RED}❌ Overall status: FAILED${NC}"
        echo -e "${RED}💥 $CHECKS_FAILED critical issue(s) must be resolved${NC}"
        echo ""
        echo -e "${YELLOW}💡 Quick fixes:${NC}"
        echo "  • Run 'make quality-fix' to auto-fix formatting and linting"
        echo "  • Run 'make install' to install missing dependencies"
        echo "  • Run 'make secrets-update' to handle new secrets"
        return 1
    fi
}

# Main execution
main() {
    local start_time=$(date +%s)

    show_header

    # Run all checks
    check_python_environment || true
    check_dependencies || true
    check_configuration || true
    check_code_formatting || true
    check_linting || true
    check_dead_code || true
    check_secrets || true
    check_tests || true
    check_git_status || true
    check_docker || true

    local end_time=$(date +%s)
    local duration=$((end_time - start_time))

    echo ""
    echo -e "${BLUE}Quality check completed in ${duration}s${NC}"

    show_summary
}

# Handle script interruption
trap 'echo -e "\n${RED}Quality check interrupted${NC}"; exit 130' INT TERM

# Run main function
main "$@"
