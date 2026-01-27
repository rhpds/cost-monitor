# Testing Strategy

The cost-monitor project uses a comprehensive multi-tier testing approach to ensure code quality and functionality.

## 🎯 Testing Tiers

### 1. **Pre-commit Smoke Tests** (~1 second)
**Automatically run on every commit via git hooks**
- 3 critical API tests covering core functionality
- Health endpoint validation
- Cost summary endpoint validation
- End-to-end data flow validation

```bash
# Run manually (same as pre-commit)
./scripts/dev.sh test-smoke
```

### 2. **Fast Development Tests** (~3 seconds)
**For rapid development iteration**
```bash
./scripts/dev.sh test-fast
```

### 3. **Full Integration Suite** (~6 seconds)
**Complete test coverage - 71 tests**
```bash
./scripts/dev.sh test-all
```

### 4. **Coverage Testing** (~8 seconds)
**Full tests with coverage reporting**
```bash
./scripts/dev.sh test
```

## 🚀 Development Workflow

### Daily Development
1. **Write code**
2. **Run `./scripts/dev.sh test-fast`** for quick validation
3. **Commit changes** - smoke tests run automatically
4. **Before PR**: Run `./scripts/dev.sh test-all` for full validation

### Quality Assurance
```bash
# Complete quality check (format, lint, tests, security)
./scripts/dev.sh quality
```

## 🔧 Git Hooks Integration

### Pre-commit Hooks (Automatic)
- **Security**: Secret scanning (detect-secrets + gitleaks)
- **Formatting**: Black code formatting + isort imports
- **Linting**: Ruff comprehensive linting
- **Type Checking**: MyPy static analysis
- **Dead Code**: Vulture detection
- **Testing**: Critical functionality smoke tests

### Hook Management
```bash
# Install hooks (done automatically with ./scripts/dev.sh install)
pre-commit install

# Run all hooks manually
pre-commit run --all-files

# Skip hooks for emergency commits
git commit --no-verify -m "emergency fix"
```

## 📊 Test Coverage

Current integration test coverage:
- **✅ 71/71 tests passing** (100% success rate)
- **API Endpoints**: 21 tests
- **Database Integration**: 22 tests
- **Cost Service Logic**: 19 tests
- **End-to-End Workflows**: 10 tests
- **Dashboard Integration**: 22 tests (skipped - requires Dash)

## 🎯 Test Categories

### API Endpoints (`tests/integration/test_api_endpoints.py`)
- Health checks and readiness probes
- Cost summary and detailed endpoints
- Provider information endpoints
- Error handling and validation

### Database Integration (`tests/integration/test_database_integration.py`)
- Connection management and pooling
- Data storage and retrieval
- AWS account name resolution
- Data consistency and performance

### Service Logic (`tests/integration/test_cost_service.py`)
- Date range preparation and caching
- Multi-provider data collection
- Response building and aggregation
- Error handling and performance

### End-to-End Workflows (`tests/integration/test_end_to_end.py`)
- Complete data collection workflows
- Multi-user concurrent access
- Cache invalidation and refresh
- Cross-endpoint data consistency

## 🚨 Debugging Failed Tests

### Pre-commit Hook Failures
```bash
# See what failed
git status

# Run specific hook manually for debugging
pre-commit run smoke-tests

# Skip hooks if needed (use sparingly)
git commit --no-verify
```

### Test Debugging
```bash
# Run with verbose output and stop on first failure
pytest tests/integration/ -vx --tb=long

# Run specific failing test
pytest tests/integration/test_api_endpoints.py::TestHealthEndpoints::test_health_live -vx

# Debug with pdb
pytest tests/integration/ --pdb
```

## ⚡ Performance Expectations

- **Pre-commit hooks total**: <10 seconds
- **Smoke tests**: <1 second
- **Fast tests**: <3 seconds
- **Full integration suite**: <6 seconds
- **Coverage tests**: <8 seconds

## 🎖️ Best Practices

1. **Run smoke tests frequently** during development
2. **Full test suite before commits** to main branches
3. **Use `--no-verify` sparingly** for emergencies only
4. **Address test failures immediately** - don't accumulate technical debt
5. **Keep tests fast** by using mocks for external dependencies

This testing strategy ensures high code quality while maintaining developer productivity! 🚀