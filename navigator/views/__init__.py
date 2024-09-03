"""
Views.

NAV aiohttp Class-Based Views.
"""
from ..libs.json import json_encoder, json_decoder
from .base import BaseHandler, BaseView
from .data import DataView
from .model import ModelView, load_models
from .mhandler import ModelHandler
from .form import FormModel
from .abstract import model_url

DEFAULT_JSON_ENCODER = json_encoder
DEFAULT_JSON_DECODER = json_decoder

__all__ = (
    'BaseHandler',
    'BaseView',
    'DataView',
    'ModelView',
    'load_models',
    'ModelHandler',
    'FormModel',
    'model_url'
)
