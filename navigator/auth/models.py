"""
Model System for Navigator Auth.

Model for User, Group and Roles for Navigator Auth.
"""
from datetime import datetime
from asyncdb.models import Model, Column
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

# # TODO: add autoincrement feature, read the last id and plus 1
# class Group(Model):
#     id: int = Column(required=True, primary_key=True)
#     name: int = Column(required=True)

#     class Meta:
#         driver = "pg"
#         dsn: str = default_dsn
#         name = "auth_group"
#         schema = "public"
#         strict = True
#         frozen = False
#         connection = None
