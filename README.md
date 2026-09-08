# ⚡ Navigator Framework

[![PyPI version](https://badge.fury.io/py/navigator-api.svg)](https://pypi.org/project/navigator-api/)
[![Python](https://img.shields.io/pypi/pyversions/navigator-api.svg)](https://pypi.org/project/navigator-api/)
[![License](https://img.shields.io/badge/license-BSD-blue.svg)](https://github.com/phenobarbital/navigator/blob/main/LICENSE)
[![Downloads](https://pepy.tech/badge/navigator-api)](https://pepy.tech/project/navigator-api)

> **A batteries-included async web framework built on aiohttp** 🚀

Navigator is a next-generation Python framework designed for building high-performance asynchronous APIs and web applications. Built on top of aiohttp and asyncio, it provides enterprise-grade features out of the box with a focus on developer productivity and application scalability.

## ✨ Key Features

- **⚡ Lightning Fast**: Built on aiohttp + uvloop for maximum performance
- **🔋 Batteries Included**: Authentication, WebSockets, templates, database connections, and more
- **🏗️ Django-style Apps**: Organize code with modular, reusable application components
- **🌐 Multi-tenant Ready**: Built-in sub-domain support for SaaS applications
- **🔧 Centralized Config**: Unified configuration management with NavConfig
- **🔌 Auto-Connections**: Automatic database connection handling with AsyncDB
- **📝 Class-based Views**: Powerful CRUD operations with ModelViews
- **🎯 Extensible**: Plugin architecture for adding custom features

## 🚀 Quick Start

### Installation

```bash
# Using uv (recommended)
uv add navigator-api[uvloop,locale]

# Using pip
pip install navigator-api[uvloop,locale]
```

### Create Your First App

```bash
# Create a new Navigator project
nav init

# Create an application
nav app create myapp

# Run the development server
nav run --debug --reload
```

### Hello Navigator

```python
# app.py
import asyncio
import uvloop
from navigator import Application
from aiohttp import web

async def hello(request):
    return web.Response(text="Hello Navigator! 🚀")

async def main():
    # Set uvloop as the event loop policy
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

    # Create Navigator application
    app = Application(enable_jinja2=True)

    # Add routes
    app.router.add_get('/', hello)

    # Enable WebSocket support
    app.add_websockets()

    # Setup and run
    return app.setup()

if __name__ == '__main__':
    asyncio.run(main())
```

## 🏗️ Architecture

### Class-based Views

Navigator provides powerful class-based views for building APIs:

```python
from navigator.views import BaseView, ModelView
from aiohttp import web
from datamodel import BaseModel

class UserView(BaseView):
    async def get(self):
        return web.json_response({"users": []})

    async def post(self):
        data = await self.request.json()
        # Process user creation
        return web.json_response({"status": "created"})

# Model-based CRUD operations
class User(BaseModel):
    name: str
    email: str
    age: int

class UserModelView(ModelView):
    model = User
    path = '/api/users'

    # Automatic CRUD operations:
    # GET /api/users - List all users
    # GET /api/users/{id} - Get specific user
    # POST /api/users - Create user
    # PUT /api/users/{id} - Update user
    # DELETE /api/users/{id} - Delete user
```

### Centralized Configuration

Navigator uses [NavConfig](https://github.com/phenobarbital/navconfig) for unified configuration management:

```python
# settings/settings.py
from navconfig import config

# Database configuration
DATABASE_URL = config.get('DATABASE_URL', 'postgresql://user:pass@localhost/db')

# Cache configuration
REDIS_URL = config.get('REDIS_URL', 'redis://localhost:6379')

# App configuration
DEBUG = config.getboolean('DEBUG', False)
SECRET_KEY = config.get('SECRET_KEY', required=True)

# Multiple environment support
ENV = config.get('ENV', 'development')  # development, staging, production
```

### Django-style Applications

Organize your code with modular applications:

```
myproject/
├── apps/
│   ├── users/
│   │   ├── __init__.py
│   │   ├── views.py
│   │   ├── models.py
│   │   ├── urls.py
│   │   └── templates/
│   └── products/
│       ├── __init__.py
│       ├── views.py
│       └── models.py
├── settings/
│   └── settings.py
└── main.py
```

```python
# apps/users/__init__.py
from navigator.applications import AppConfig

class UsersConfig(AppConfig):
    name = 'users'
    path = '/api/users'

    def ready(self):
        # App initialization code
        pass
```

### Database Integration

Navigator integrates seamlessly with [AsyncDB](https://github.com/phenobarbital/asyncdb) for database operations:

```python
from navigator.views import ModelView
from asyncdb.models import Model

# Define your model
class User(Model):
    name: str
    email: str
    created_at: datetime

    class Meta:
        name = 'users'
        schema = 'public'

# Create CRUD API automatically
class UserAPI(ModelView):
    model = User
    path = '/api/users'

    # Optional: Add custom validation
    async def validate_payload(self, data):
        if 'email' not in data:
            raise ValueError("Email is required")
        return data

    # Optional: Add custom callbacks
    async def _post_callback(self, response, model):
        # Send welcome email, log activity, etc.
        pass
```

### WebSocket Support

Real-time features with built-in WebSocket support:

```python
from navigator import Application
from navigator.services.ws import WebSocketHandler

class ChatHandler(WebSocketHandler):
    async def on_message(self, message):
        # Broadcast message to all connected clients
        await self.broadcast(message)

app = Application()
app.add_websockets()
app.router.add_websocket('/ws/chat', ChatHandler)
```

## 🔌 Extensions

Navigator's extension system allows you to add powerful features:

### Authentication Extension

```python
# Install: pip install navigator-auth
from navigator_auth import AuthConfig

class MyApp(Application):
    def configure(self):
        # Add JWT authentication
        self.add_extension(AuthConfig, {
            'secret_key': 'your-secret-key',
            'algorithm': 'HS256',
            'token_expiration': 3600
        })
```

### Admin Interface

```python
# Coming soon: Django-style admin interface
from navigator.admin import admin_site
from .models import User, Product

admin_site.register(User)
admin_site.register(Product)

app.include_router(admin_site.router, prefix='/admin')
```

## 🛠️ CLI Tools

Navigator includes powerful CLI tools for development:

```bash
# Project management
nav init                        # Create new project
nav app create myapp            # Create new application

# Development
nav run                       # Start development server
nav shell                     # Interactive shell

```

## 📦 Available Extensions

Navigator supports various optional dependencies:

```bash
# Performance optimizations
navigator-api[uvloop]         # uvloop for better async performance

# Internationalization
navigator-api[locale]         # Babel for i18n support

# Production deployment
navigator-api[gunicorn]       # Gunicorn WSGI server

# All features
navigator-api[all]            # Install all optional dependencies
```

## 🚀 Deployment

### AWS App Runner

Navigator includes built-in support for AWS App Runner deployment:

```yaml
# apprunner.yaml
version: 1.0
runtime: python3
build:
  commands:
    build:
      - pip install -r requirements.txt
      - python setup.py build_ext --inplace
run:
  runtime-version: '3.11'
  command: 'nav run --port 8080'
  network:
    port: 8080
    env: PORT
```

### Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN python setup.py build_ext --inplace

EXPOSE 8000
CMD ["nav", "run", "--port", "8000"]
```

## 📋 Requirements

- **Python**: 3.9+ (3.11+ recommended)
- **Dependencies**:
  - aiohttp >= 3.10.0
  - asyncio (built-in)
  - uvloop >= 0.21.0 (optional, recommended; not installed on Windows — see
    [Platform & Wheel Support](#-platform--wheel-support))

## 🖥️ Platform & Wheel Support

Navigator ships **prebuilt, Cython-compiled wheels** for:

| Platform | Wheel tag | CPython versions |
|---|---|---|
| Linux x86_64 | `manylinux_2_28_x86_64` | 3.11, 3.12, 3.13, 3.14 |
| Windows AMD64 | `win_amd64` | 3.11, 3.12, 3.13, 3.14 |

Every published wheel bundles Navigator's two compiled extensions —
`navigator.types` and `navigator.utils.types` — as a platform-native
`.so` (Linux) or `.pyd` (Windows) file; the release pipeline fails before
publication if either extension is missing from a wheel. **No Rust,
PyO3, or maturin toolchain is used or required** — Navigator's native
code is Cython-only, built with `setuptools` from `setup.py`.

**Not currently built or published**: macOS, `win32`, `win_arm64`,
free-threaded CPython builds, `i686`, `musllinux`, and PyPy. If your
platform isn't listed above, install from the source distribution
instead (`pip install navigator-api --no-binary navigator-api`), which
requires a C/C++ compiler and Cython locally.

**Optional integrations may have narrower platform support than the
core package.** In particular:

- `uvloop` (the `navigator-api[uvloop]` / `navigator-api[production]`
  extras) is excluded on Windows — `asyncdb`'s own `uvloop` extra is
  likewise never pulled in unconditionally, so a Windows install of
  Navigator's base package never tries to resolve uvloop. Navigator
  falls back to the standard asyncio event loop policy there.
- Not every optional database/provider integration under
  `navigator-api[...]` is guaranteed to work on Windows or under
  CPython 3.14; check the individual dependency's own platform support
  before relying on it in production.

## 🧑‍🔧 Building From Source (Maintainers)

Navigator's two Cython extensions are compiled by `setup.py` via
`setuptools`; `pyproject.toml`'s `[build-system].requires` lists only
what that build actually needs (`setuptools`, `Cython`, `wheel`,
`setuptools_scm`) — `navconfig`, a legitimate *runtime* dependency, is
never required just to compile the extensions.

Importing `navigator` — including in an isolated build/test environment
with no project scaffolding — never crashes on a missing `navconfig`
project. Directly exercising `navigator.types` / `navigator.utils.types`
against a real `navconfig`-backed configuration (as the release
pipeline's post-publish smoke test does) requires the project markers
`navconfig` expects: an `env/<ENV>/.env` file, a top-level `.env` file,
`pyproject.toml`, and `etc/config.ini`, with `SITE_ROOT` (and optionally
`ENV`) pointing at that scaffolded directory. See
`tests/test_release_wheel.py` for a reusable fixture that builds this
layout, and `.github/workflows/release.yml` for how the release
pipeline scaffolds it before running its own smoke tests.

## 🧪 Testing

```bash
# Install development dependencies
uv add --dev pytest pytest-asyncio coverage

# Run tests
pytest

# Run with coverage
pytest --cov=navigator tests/
```

## 📚 Documentation

- **Official Documentation**: [navigator-api.readthedocs.io](https://navigator-api.readthedocs.io) *(coming soon)*
- **API Reference**: Available in source code docstrings
- **Examples**: Check the [examples/](examples/) directory
- **Tutorial**: See [Quick Start](#-quick-start) section above

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/phenobarbital/navigator.git
cd navigator

# Create development environment
uv venv --python 3.11 .venv
source .venv/bin/activate

# Install development dependencies
uv sync --dev

# Install pre-commit hooks
pre-commit install

# Run tests
pytest
```

## 📜 License

Navigator is licensed under the **BSD 3-Clause License**. See [LICENSE](LICENSE) for details.

## 🙏 Credits

Navigator is built on top of these amazing projects:

- [aiohttp](https://docs.aiohttp.org/) - Async HTTP client/server framework
- [asyncio](https://docs.python.org/3/library/asyncio.html) - Asynchronous I/O framework
- [uvloop](https://github.com/MagicStack/uvloop) - Fast asyncio event loop
- [Jinja2](https://jinja.palletsprojects.com/) - Template engine
- [AsyncDB](https://github.com/phenobarbital/asyncdb) - Database connectivity
- [NavConfig](https://github.com/phenobarbital/navconfig) - Configuration management

## 🔗 Links

- **PyPI**: https://pypi.org/project/navigator-api/
- **GitHub**: https://github.com/phenobarbital/navigator
- **Issues**: https://github.com/phenobarbital/navigator/issues
- **Discussions**: https://github.com/phenobarbital/navigator/discussions

---

Made with ❤️ by the Navigator team. Built for the async future of web development.
