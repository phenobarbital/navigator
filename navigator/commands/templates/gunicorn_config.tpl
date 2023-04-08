# Gunicorn Configuration File
import multiprocessing
import navconfig

cores = multiprocessing.cpu_count() / 2
APP_HOST = navconfig.config.get('APP_HOST', fallback='0.0.0.0')
APP_PORT = navconfig.config.get('APP_PORT', fallback=5000)
APP_WORKERS = navconfig.config.get('APP_WORKERS', fallback=cores)

# workers = int(APP_WORKERS)
workers = 8
threads = 8
max_request = 1000
max_requests_jitter = 10
bind = f"{APP_HOST}:{APP_PORT}"
backlog = 2048
worker_connections = 1000
timeout = 360
keepalive = 2
worker_class = 'aiohttp.worker.GunicornUVLoopWebWorker'
