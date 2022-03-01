"""
Model System for Navigator Auth.

Model for User, Group and Roles for Navigator Auth.
"""
import uuid
import asyncio
import logging
from asyncdb.models import Model, Column, Field
from typing import (
    Optional,
    List,
    Dict,
    Union,
    Tuple,
    Any,
    Callable
)
from dataclasses import InitVar
from datetime import datetime
from navigator.conf import default_dsn, USERS_TABLE


class User(Model):
    """Basic User notation."""

    user_id: int = Column(required=False, primary_key=True)
    first_name: str
    last_name: str
    email: str = Column(required=False, max=254)
    password: str = Column(required=False, max=128)
    last_login: datetime = Column(required=False)
    username: str = Column(required=False)
    is_superuser: bool = Column(required=True, default=False)
    is_active: bool = Column(required=True, default=True)
    is_new: bool = Column(required=True, default=True)
    title: str = Column(equired=False, max=90)
    registration_key: str = Column(equired=False, max=512)
    reset_pwd_key: str = Column(equired=False, max=512)
    avatar: str = Column(max=512)

    def __getitem__(self, item):
        return getattr(self, item)

    @property
    def display_name(self):
        return f"{self.first_name} {self.last_name}"

    class Meta:
        driver = "pg"
        dsn: str = default_dsn
        name = USERS_TABLE
        schema = "public"
        strict = True
        frozen = False
        connection = None


# TODO: add autoincrement feature, read the last id and plus 1
class Group(Model):
    id: int = Column(required=True, primary_key=True)
    name: int = Column(required=True)

    class Meta:
        driver = "pg"
        dsn: str = default_dsn
        name = "auth_group"
        schema = "public"
        strict = True
        frozen = False
        connection = None


# class UserGroup(Model):
#     member_id: int = Column(required=True, primary_key=True)
#     user_id: User = Column(required=True)
#     group_id: Group = Column(required=True)
#
#     class Meta:
#         driver = 'pg'
#         name = 'auth_membership'
#         schema = 'public'
#         app_label = 'troc'
#         strict = True
#         frozen = False
#
# class Role(Model):
#     role_id: int = Column(required=True, primary_key=True)
#     rolename: str = Column(required=True, unique=True)
#     role: str = Column(required=True, unique=True, comment="Role Slug")
#     program_id: int = Column(required=False, default=1)
#
#     class Meta:
#         driver = 'pg'
#         name = 'auth_roles'
#         schema = 'public'
#         app_label = 'troc'
#         strict = True
#         frozen = False

class AuthUser(Model):
    """AuthUser

    Model for any Authenticated User.
    """
    id: Any
    first_name: str
    last_name: str
    email: str
    username: str
    # roles: List[Role]
    # group: List[UserGroup]
    # orgs: List[Organization]
    data: InitVar[Dict] = Column(required=False, default_factory=dict)
    userdata: Dict  = Column(required=False, default_factory={})
    is_authenticated: bool = Column(equired=False, default=False)

    class Meta:
        strict = False
        frozen = False
        connection = None
    
    def __post_init__(self, data):
        self.userdata = data
        for key, value in data.items():
            self.create_field(key, value)

    def create_field(self, name: str, value: Any) -> None:
        # create a new Field on Model (when strict is False).            
        f = Field(required=False, default=value)
        f.name = name
        f.type = type(value)
        self.__columns__[name] = f
        setattr(self, name, value)
        
    def set(self, name: str, value: Any) -> None:
        # alias for "create_field"
        self.create_field(name, value)

    """
    User Methods.
    """
    def groups(self, grp: List):
        self.group = grp
        
    def organizations(self, orgs: List):
        self.orgs = orgs