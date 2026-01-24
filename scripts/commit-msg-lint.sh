#!/bin/bash
# Commit Message Linting for Cost Monitor
# Enforces conventional commit standards and quality guidelines

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Configuration
COMMIT_MSG_FILE="${1:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_rule() {
    echo -e "${PURPLE}[RULE]${NC} $1"
}

# Show usage
show_usage() {
    echo "Commit Message Linting Tool"
    echo "=========================="
    echo ""
    echo "Usage:"
    echo "  $0 <commit-msg-file>     # Lint commit message from file"
    echo "  $0 --message 'msg'       # Lint commit message directly"
    echo "  $0 --help               # Show this help"
    echo ""
    echo "Examples:"
    echo "  $0 .git/COMMIT_EDITMSG"
    echo "  $0 --message 'feat: add user authentication'"
    echo ""
    echo "This tool enforces conventional commit standards:"
    echo "  - Proper format: type(scope): description"
    echo "  - Valid types: feat, fix, docs, style, refactor, test, chore"
    echo "  - Length limits and style guidelines"
}

# Parse command line arguments
parse_args() {
    if [[ $# -eq 0 ]] || [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
        show_usage
        exit 0
    fi

    if [[ "${1:-}" == "--message" ]] && [[ $# -ge 2 ]]; then
        COMMIT_MSG="$2"
        COMMIT_MSG_FILE=""
    elif [[ -f "${1:-}" ]]; then
        COMMIT_MSG_FILE="$1"
        COMMIT_MSG=""
    else
        log_error "Invalid arguments or commit message file not found: ${1:-}"
        show_usage
        exit 1
    fi
}

# Read commit message
get_commit_message() {
    local message=""

    if [[ -n "$COMMIT_MSG_FILE" ]]; then
        if [[ ! -f "$COMMIT_MSG_FILE" ]]; then
            log_error "Commit message file not found: $COMMIT_MSG_FILE"
            exit 1
        fi
        message=$(cat "$COMMIT_MSG_FILE")
    else
        message="$COMMIT_MSG"
    fi

    # Get first line (subject)
    echo "$message" | head -n1
}

# Validate conventional commit format
validate_conventional_commit() {
    local subject="$1"

    log_info "Validating conventional commit format..."

    # Define valid types
    local valid_types="feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert"

    # Main pattern: type(scope): description
    local pattern="^(${valid_types})(\([a-z0-9-]+\))?: .+"

    if [[ ! "$subject" =~ $pattern ]]; then
        log_error "Commit message doesn't follow conventional commit format"
        log_rule "Expected format: type(scope): description"
        log_rule "Valid types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert"
        log_rule "Example: feat(auth): add user authentication system"
        return 1
    fi

    log_success "Conventional commit format is correct"
    return 0
}

# Validate commit message length
validate_length() {
    local subject="$1"
    local length=${#subject}

    log_info "Validating commit message length..."

    # Subject line length check
    if [[ $length -lt 10 ]]; then
        log_error "Commit subject too short: $length characters (minimum 10)"
        log_rule "Provide a descriptive commit message"
        return 1
    fi

    if [[ $length -gt 50 ]]; then
        log_warning "Commit subject is long: $length characters (recommended max 50)"
        log_rule "Consider shortening the commit message"
        if [[ $length -gt 72 ]]; then
            log_error "Commit subject too long: $length characters (maximum 72)"
            return 1
        fi
    fi

    log_success "Commit message length is appropriate"
    return 0
}

# Validate commit message style
validate_style() {
    local subject="$1"

    log_info "Validating commit message style..."

    # Check for proper capitalization after colon
    if [[ "$subject" =~ :[[:space:]]*[A-Z] ]]; then
        log_error "Don't capitalize after colon in commit subject"
        log_rule "Use lowercase after colon: 'feat(auth): add user login'"
        return 1
    fi

    # Check for ending period
    if [[ "$subject" =~ \.$   ]]; then
        log_warning "Remove trailing period from commit subject"
        log_rule "Don't end commit subject with a period"
    fi

    # Check for imperative mood indicators
    local bad_words="added|fixed|updated|changed|implemented|created"
    if [[ "$subject" =~ ($bad_words) ]]; then
        log_warning "Use imperative mood in commit messages"
        log_rule "Use 'add' not 'added', 'fix' not 'fixed'"
        log_rule "Think: 'This commit will...' + your message"
    fi

    # Check for common typos and issues
    if [[ "$subject" =~ [[:space:]]{2,} ]]; then
        log_error "Remove multiple spaces in commit message"
        return 1
    fi

    if [[ "$subject" =~ ^[[:space:]] ]] || [[ "$subject" =~ [[:space:]]$ ]]; then
        log_error "Remove leading/trailing spaces from commit message"
        return 1
    fi

    log_success "Commit message style is good"
    return 0
}

# Validate commit type appropriateness
validate_commit_type() {
    local subject="$1"

    log_info "Validating commit type appropriateness..."

    # Extract type
    local type=""
    if [[ "$subject" =~ ^([a-z]+) ]]; then
        type="${BASH_REMATCH[1]}"
    fi

    # Type-specific validations
    case "$type" in
        "feat")
            if [[ ! "$subject" =~ (add|implement|create|new) ]]; then
                log_warning "Feature commits should describe what's being added"
                log_rule "Example: 'feat(auth): add OAuth2 authentication'"
            fi
            ;;
        "fix")
            if [[ ! "$subject" =~ (fix|resolve|correct|patch) ]]; then
                log_warning "Fix commits should describe what's being fixed"
                log_rule "Example: 'fix(api): resolve authentication timeout'"
            fi
            ;;
        "docs")
            if [[ ! "$subject" =~ (update|add|improve|fix|document) ]]; then
                log_warning "Docs commits should describe documentation changes"
                log_rule "Example: 'docs(readme): update installation instructions'"
            fi
            ;;
        "refactor")
            if [[ "$subject" =~ (add|remove|new|delete) ]]; then
                log_warning "Refactor shouldn't add/remove functionality"
                log_rule "Use 'feat' or 'fix' for functional changes"
            fi
            ;;
        "test")
            if [[ ! "$subject" =~ (test|spec|coverage) ]]; then
                log_warning "Test commits should mention testing"
                log_rule "Example: 'test(auth): add unit tests for login'"
            fi
            ;;
    esac

    log_success "Commit type is appropriate"
    return 0
}

# Validate scope appropriateness for project
validate_scope() {
    local subject="$1"

    log_info "Validating scope appropriateness..."

    # Extract scope if present
    local scope=""
    if [[ "$subject" =~ \(([a-z0-9-]+)\) ]]; then
        scope="${BASH_REMATCH[1]}"
    fi

    if [[ -n "$scope" ]]; then
        # Valid scopes for this project
        local valid_scopes=(
            "auth" "api" "dashboard" "providers" "aws" "azure" "gcp"
            "alerts" "monitoring" "config" "cli" "docs" "tests"
            "deps" "ci" "docker" "prometheus" "pydantic" "validation"
            "hooks" "quality" "security" "performance"
        )

        local scope_valid=false
        for valid_scope in "${valid_scopes[@]}"; do
            if [[ "$scope" == "$valid_scope" ]]; then
                scope_valid=true
                break
            fi
        done

        if [[ "$scope_valid" == false ]]; then
            log_warning "Uncommon scope: '$scope'"
            log_rule "Common scopes: ${valid_scopes[*]:0:10}..."
            log_rule "Consider using a more standard scope or omit if unclear"
        else
            log_success "Scope '$scope' is appropriate"
        fi
    else
        log_info "No scope specified (optional)"
    fi

    return 0
}

# Check for breaking changes
check_breaking_changes() {
    local full_message="$1"

    log_info "Checking for breaking changes..."

    # Check for breaking change indicators
    if [[ "$full_message" =~ BREAKING[[:space:]]CHANGE ]] || [[ "$full_message" =~ ! ]]; then
        log_warning "Breaking change detected!"
        log_rule "Ensure breaking changes are properly documented"
        log_rule "Consider major version bump"
    fi

    return 0
}

# Suggest improvements
suggest_improvements() {
    local subject="$1"

    log_info "Suggesting improvements..."

    # Extract type and description
    local type=""
    local description=""
    if [[ "$subject" =~ ^([a-z]+)(\([a-z0-9-]+\))?:[[:space:]]*(.+) ]]; then
        type="${BASH_REMATCH[1]}"
        description="${BASH_REMATCH[3]}"
    fi

    # Specific suggestions based on content
    if [[ "$description" =~ ^update ]]; then
        log_rule "Instead of 'update', be more specific: 'add', 'fix', 'improve'"
    fi

    if [[ "$description" =~ ^change ]]; then
        log_rule "Instead of 'change', be more specific about what changed"
    fi

    if [[ "$description" =~ ^minor ]]; then
        log_rule "Avoid 'minor' - all commits should have clear purpose"
    fi

    if [[ "$description" =~ (bug|issue) ]] && [[ "$type" != "fix" ]]; then
        log_rule "Consider using 'fix' type for bug-related commits"
    fi

    if [[ "$description" =~ (feature|functionality) ]] && [[ "$type" != "feat" ]]; then
        log_rule "Consider using 'feat' type for new features"
    fi

    return 0
}

# Main validation function
validate_commit_message() {
    local full_message="$1"
    local subject
    subject=$(echo "$full_message" | head -n1)

    local errors=0

    echo "🔍 Commit Message Validation"
    echo "=========================="
    echo "Subject: $subject"
    echo ""

    # Run all validations
    validate_conventional_commit "$subject" || ((errors++))
    echo ""

    validate_length "$subject" || ((errors++))
    echo ""

    validate_style "$subject" || ((errors++))
    echo ""

    validate_commit_type "$subject" || true  # warnings only
    echo ""

    validate_scope "$subject" || true  # warnings only
    echo ""

    check_breaking_changes "$full_message" || true  # warnings only
    echo ""

    suggest_improvements "$subject" || true  # suggestions only
    echo ""

    # Summary
    if [[ $errors -eq 0 ]]; then
        log_success "Commit message validation passed! ✨"
        echo ""
        echo "🎉 Your commit message follows best practices."
        return 0
    else
        log_error "Commit message validation failed with $errors error(s)"
        echo ""
        echo "💡 Quick fixes:"
        echo "  • Follow format: type(scope): description"
        echo "  • Use lowercase after colon"
        echo "  • Use imperative mood (add, not added)"
        echo "  • Keep subject under 50 characters"
        echo ""
        return 1
    fi
}

# Main execution
main() {
    parse_args "$@"

    local commit_message
    commit_message=$(get_commit_message)

    if [[ -z "$commit_message" ]]; then
        log_error "No commit message found"
        exit 1
    fi

    # Skip validation for merge commits
    if [[ "$commit_message" =~ ^Merge ]]; then
        log_info "Skipping validation for merge commit"
        exit 0
    fi

    # Skip validation for revert commits
    if [[ "$commit_message" =~ ^Revert ]]; then
        log_info "Skipping validation for revert commit"
        exit 0
    fi

    # Skip validation for auto-generated commits
    if [[ "$commit_message" =~ ^(WIP|fixup|squash) ]]; then
        log_info "Skipping validation for auto-generated commit"
        exit 0
    fi

    validate_commit_message "$commit_message"
}

# Run main function
main "$@"
