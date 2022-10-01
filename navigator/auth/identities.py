from typing import (
    Any,
    List,
    Optional
)
from dataclasses import InitVar
from slugify import slugify
from datamodel import BaseModel, Column


class Group(BaseModel):
    """Group.

    Association (group) were users belongs to.
    """
    group: str = Column(required=True)

    class Meta:
        strict = True
        frozen = False

# create a Guest Group.
Guest = Group(group = 'guest')


class Organization(BaseModel):
    org_id: str
    organization: str
    slug: str

    def __post_init__(self) -> None:
        super(Organization, self).__post_init__()
        if not self.slug:
            self.slug = slugify(self.organization)

    class Meta:
        strict = True
        frozen = False

class Program(BaseModel):
    program_id: int
    program_name: str
    program_slug: str

    def __post_init__(self) -> None:
        super(Program, self).__post_init__()
        if not self.program_slug:
            self.program_slug = slugify(self.program_name)

    class Meta:
        strict = True
        frozen = False


class Identity(BaseModel):
    """Identity.

    Describe an Authenticated Entity on Navigator.
    """
    id: Any = Column(required=True)
    auth_method: str = None
    access_token: Optional[str] = None
    enabled: bool = Column(required=True, default=True)
    data: InitVar = Column(required=False, default_factory=dict)
    is_authenticated: bool = Column(equired=False, default=False)
    userdata: dict  = Column(required=False, default_factory={})

    def __post_init__(self, data): # pylint: disable=W0221
        self.userdata = data
        for key, value in data.items():
            self.create_field(key, value)

    def set(self, name: str, value: Any) -> None:
        # alias for "create_field"
        self.create_field(name, value)

    class Meta:
        strict = False
        frozen = False


class AuthUser(Identity):
    """AuthUser

    Model for any Authenticated User.
    """
    first_name: str
    last_name: str
    name: str
    email: str
    username: str
    groups: List[Group] = Column(required=False, default_factory=list)
    organizations: List[Organization] = Column(required=False, default_factory=list)
    superuser: bool = Column(required=True, default=False)

    def __post_init__(self, data) -> None:
        super(AuthUser, self).__post_init__(data)
        if self.groups is not None:
            groups = self.groups.copy()
            self.groups = []
            for group in groups:
                self.add_group(group)
        else:
            self.groups = []
        self.organizations = []

    ### User Methods.
    def add_group(self, group: Group):
        if isinstance(group, str):
            group = Group(group=group)
        self.groups.append(group)
