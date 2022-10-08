from navconfig import config, BASE_DIR


STATIC_DIR = config.get('STATIC_DIR', fallback='static/')
APP_DIR = BASE_DIR.joinpath("apps")
