from navconfig import config


### Google Service Credentials:
GA_SERVICE_ACCOUNT_NAME = config.get('GA_SERVICE_ACCOUNT_NAME', fallback="google.json")
GA_SERVICE_PATH = config.get('GA_SERVICE_PATH', fallback="google/")

## Google API:
GOOGLE_PLACES_API_KEY = config.get('GOOGLE_PLACES_API_KEY')
