[general]
CONFIG_FILE=etc/navigator.ini

[api]
API_HOST=nav-api.dev.local:5000

[database]
DBENGINE=navigator.pgschema
DBUSER=postgres
DBPWD=12345678
DBHOST=nav-api.dev.local
DBPORT=5432
DBNAME=navigator

[cache]
CACHEHOST=127.0.0.1
CACHEPORT=6379
QUERYSET_DB=0
MEMCACHE_HOST=127.0.0.1
MEMCACHE_PORT=11211
CACHE_PREFIX=local

[debug]
PRODUCTION=false
DEBUG=true
