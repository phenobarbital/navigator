from navconfig.logging import logging
from aiohttp import web
from .types import BaseApp


#######################
##
## APPS CONFIGURATION
##
#######################
def app_startup(app_list: list, app: web.Application, context: dict = None, **kwargs):
    """ Initialize all Apps in the existing Installation."""
    for apps in app_list:
        obj = None
        app_name, app_class = apps # splitting the tuple
        try:
            instance_app = None
            name = app_name.split(".")[1]
            if app_class is not None:
                obj = getattr(app_class, name)
                instance_app = obj(app_name=name, context=context, **kwargs)
                domain = getattr(instance_app, "domain", None)
            else:
                ## TODO: making a default App configurable.
                instance_app = BaseApp(app_name=name, context=context, **kwargs)
                instance_app.__class__.__name__ = name
                domain = None
            sub_app = instance_app.App
            if domain:
                app.add_domain(domain, sub_app)
                # TODO: adding as sub-app as well
            else:
                app.add_subapp(f"/{name}/", sub_app)
            # TODO: build automatic documentation
            try:
                # can I add Main to subApp?
                sub_app['Main'] = app
                for name, ext in app.extensions.items():
                    if name not in ('database', 'redis', 'memcache'):
                        # can't share asyncio-based connections prior inicialization
                        sub_app[name] = ext
                        sub_app.extensions[name] = ext
            except (KeyError, AttributeError) as err:
                logging.warning(err)
        except ImportError as err:
            logging.warning(err)
            continue
