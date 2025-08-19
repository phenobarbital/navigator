# Navigator Makefile
# This Makefile provides a set of commands to manage the Navigator project.

.PHONY: venv install develop setup dev release format lint test clean distclean lock sync

# Python version to use
PYTHON_VERSION := 3.11

# Auto-detect available tools
HAS_UV := $(shell command -v uv 2> /dev/null)
HAS_PIP := $(shell command -v pip 2> /dev/null)

# Install uv for faster workflows
install-uv:
	curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "uv installed! You may need to restart your shell or run 'source ~/.bashrc'"
	@echo "Then re-run make commands to use faster uv workflows"

# Create virtual environment
venv:
	uv venv --python $(PYTHON_VERSION) .venv
	@echo 'run `source .venv/bin/activate` to start develop with Navigator.'

# Install production dependencies using lock file
install:
	uv sync --frozen --no-dev
	uv pip install navigator-auth
	uv pip install navigator-api[uvloop,locale]
	@echo "Production dependencies installed. Use 'make develop' for development setup."

# Generate lock files (uv only)
lock:
ifdef HAS_UV
	uv lock
else
	@echo "Lock files require uv. Install with: pip install uv"
endif

# Install all dependencies including dev dependencies
develop:
	uv sync --frozen --extra dev

# Alternative: install without lock file (faster for development)
develop-fast:
	uv pip install -e .[dev]

# Setup development environment from requirements file (if you still have one)
setup:
	uv pip install -r requirements/requirements-dev.txt

# Install in development mode using flit (if you want to keep flit)
dev:
	uv pip install flit
	flit install --symlink

# Build and publish release
release: lint test clean
	uv build
	uv publish

# Alternative release using flit
release-flit: lint test clean
	flit publish

# Format code
format:
	uv run black navigator
	uv run isort navigator

# Lint code
lint:
	uv run pylint --rcfile .pylint navigator/*.py
	uv run black --check navigator
	uv run isort --check-only navigator

# Run tests with coverage
test:
	uv run coverage run -m pytest tests/
	uv run coverage report
	uv run mypy navigator/*.py

# Alternative test command using pytest directly
test-pytest:
	uv run pytest tests/

# Add new dependency and update lock file
add:
	@if [ -z "$(pkg)" ]; then echo "Usage: make add pkg=package-name"; exit 1; fi
	uv add $(pkg)

# Add development dependency
add-dev:
	@if [ -z "$(pkg)" ]; then echo "Usage: make add-dev pkg=package-name"; exit 1; fi
	uv add --dev $(pkg)

# Remove dependency
remove:
	@if [ -z "$(pkg)" ]; then echo "Usage: make remove pkg=package-name"; exit 1; fi
	uv remove $(pkg)

# Compile Cython extensions using setup.py
build-cython:
	@echo "Compiling Cython extensions..."
	python setup.py build_ext

# Build Cython extensions in place (for development)
build-inplace:
	@echo "Building Cython extensions in place..."
	python setup.py build_ext --inplace

# Full build using uv
build: clean
	@echo "Building package with uv..."
	uv build

# Update all dependencies
update:
	uv lock --upgrade

# Show project info
info:
	uv tree

# Clean build artifacts
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete
	find . -name "*.so" -delete
	find . -type d -name __pycache__ -delete
	find . -type f -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "Clean complete."

# Remove virtual environment
distclean:
	rm -rf .venv
	rm -rf uv.lock

# Navigator-specific commands
nav-new:
	@if [ -z "$(name)" ]; then echo "Usage: make nav-new name=project-name"; exit 1; fi
	uv run nav new $(name)

nav-startapp:
	@if [ -z "$(name)" ]; then echo "Usage: make nav-startapp name=app-name"; exit 1; fi
	uv run nav startapp $(name)

nav-run:
	@echo "Starting Navigator development server..."
	uv run nav run

nav-shell:
	@echo "Starting Navigator shell..."
	uv run nav shell

# Database migrations (if using asyncdb)
migrate:
	uv run nav migrate

# Locale support
locale-extract:
	@echo "Extracting translatable strings..."
	uv run pybabel extract --mapping=babel.cfg --output-file=locale/messages.pot .

locale-update:
	@echo "Updating translations..."
	uv run pybabel update --input-file=locale/messages.pot --output-dir=locale

locale-compile:
	@echo "Compiling translations..."
	uv run pybabel compile --domain=nav --directory=locale --use-fuzzy

# Version management
bump-patch:
	@python -c "import re; \
	content = open('navigator/__init__.py').read(); \
	version = re.search(r'__version__ = \"(.+)\"', content).group(1); \
	parts = version.split('.'); \
	parts[2] = str(int(parts[2]) + 1); \
	new_version = '.'.join(parts); \
	new_content = re.sub(r'__version__ = \".+\"', f'__version__ = \"{new_version}\"', content); \
	open('navigator/__init__.py', 'w').write(new_content); \
	print(f'Version bumped to {new_version}')"

bump-minor:
	@python -c "import re; \
	content = open('navigator/__init__.py').read(); \
	version = re.search(r'__version__ = \"(.+)\"', content).group(1); \
	parts = version.split('.'); \
	parts[1] = str(int(parts[1]) + 1); \
	parts[2] = '0'; \
	new_version = '.'.join(parts); \
	new_content = re.sub(r'__version__ = \".+\"', f'__version__ = \"{new_version}\"', content); \
	open('navigator/__init__.py', 'w').write(new_content); \
	print(f'Version bumped to {new_version}')"

bump-major:
	@python -c "import re; \
	content = open('navigator/__init__.py').read(); \
	version = re.search(r'__version__ = \"(.+)\"', content).group(1); \
	parts = version.split('.'); \
	parts[0] = str(int(parts[0]) + 1); \
	parts[1] = '0'; \
	parts[2] = '0'; \
	new_version = '.'.join(parts); \
	new_content = re.sub(r'__version__ = \".+\"', f'__version__ = \"{new_version}\"', content); \
	open('navigator/__init__.py', 'w').write(new_content); \
	print(f'Version bumped to {new_version}')"

help:
	@echo "Available targets:"
	@echo "  venv         - Create virtual environment"
	@echo "  install      - Install production dependencies"
	@echo "  develop      - Install development dependencies"
	@echo "  build        - Build package"
	@echo "  release      - Build and publish package"
	@echo "  test         - Run tests"
	@echo "  format       - Format code"
	@echo "  lint         - Lint code"
	@echo "  clean        - Clean build artifacts"
	@echo "  install-uv   - Install uv"
	@echo "  build-inplace - Build Cython extensions in place"
	@echo ""
	@echo "Navigator-specific targets:"
	@echo "  nav-new      - Create new Navigator project"
	@echo "  nav-startapp - Create new Navigator app"
	@echo "  nav-run      - Start development server"
	@echo "  nav-shell    - Start Navigator shell"
	@echo "  migrate      - Run database migrations"
	@echo "  locale-*     - Locale management commands"
