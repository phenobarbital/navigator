# get settings
try:
    from settings.settings import *
except ImportError:
    print('Its recommended to use a settings/settings module to customize Navigator Configuration')

"""
User Local Settings
"""
try:
    from settings.local_settings import *
except ImportError:
    pass
