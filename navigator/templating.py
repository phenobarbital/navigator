from pathlib import Path
from io import BytesIO
from jinja2 import (
    Environment,
    FileSystemLoader,
    ModuleLoader
)
from typing import (
    Dict,
    Optional
)

# TODO: implementing a bytecode-cache on redis or memcached
jinja_config = {
    'autoescape': True,
    'enable_async': False,
    'extensions': [
        'jinja2.ext.autoescape',
        'jinja2.ext.with_',
        'jinja2.ext.i18n'
    ]
}

class TemplateParser(object):
    """
    TemplateParser.

    This is a wrapper for the Jinja2 template engine.
    """
    path = None
    template = None
    filename = None
    config = None
    env = None
    cache = None
    def __init__(self, directory: Path, **kwargs):
        self.path = directory.resolve()
        if not self.path.exists():
            raise RuntimeError(
                f'NAVIGATOR: template directory {self.path} does not exist'
            )
        if 'config' in kwargs:
            self.config = {**jinja_config, **kwargs['config']}
        else:
            self.config = jinja_config
        # create loader:
        templateLoader = FileSystemLoader(
            searchpath=[str(self.path)]
        )
        # initialize the environment
        try:
            # TODO: check the bug ,encoding='ANSI'
            self.env = Environment(
                loader=templateLoader,
                **self.config
            )
            compiled_path = str(self.path.joinpath('.compiled'))
            self.env.compile_templates(
                target=compiled_path, zip='deflated'
            )
        except Exception as err:
            raise RuntimeError(
                f'NAV: Error loading Template Environment: {err}'
            )

    def get_template(self, filename: str):
        """
        Get a template from Template Environment using the Filename.
        """
        self.template = self.env.get_template(str(filename))
        return self.template

    @property
    def environment(self):
        """
        Property to return the current Template Environment.
        """
        return self.env

    def render(self, filename: str, params: Optional[Dict] = {}) -> str:
        result = None
        try:
            self.template = self.env.get_template(
                str(filename)
            )
            result = self.template.render(**params)
        except Exception as err:
            raise RuntimeError(
                f'NAV: Error rendering template: {filename}, error: {err}'
            )
        finally:
            return result
