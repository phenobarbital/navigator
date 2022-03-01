from collections.abc import MutableMapping
from typing import Any, Union, List, Dict, Tuple, Iterator, Iterable

class ClassDict(MutableMapping):
    def __init__(self, data: Union[Tuple, Dict] = (), default: Any = None):
        self._columns: list = []
        self.mapping = {}
        self.default = default
        self.update(data)
        self._columns = list(self.mapping.keys())
        print(self.mapping, self._columns)

    def update(self, items: Iterable):
        for key, value in items.items():
            self.mapping[key] = value

    def __missing__(self, key):
        return self.default

    def items(self) -> zip:  # type: ignore
        return zip(self._columns, self.mapping)

    @property
    def keys(self) -> List:
        return self._columns

    def set(self, key, value) -> None:
        self.mapping[key] = value
        if not key in self._columns:
            self._columns.append(key)

    """
     Section: Simple magic methods
    """
    def __len__(self) -> int:
        return len(self.mapping)

    def __str__(self) -> str:
        return f"<{type(self).__name__}({self.mapping})>"

    def __repr__(self) -> str:
        return f"<{type(self).__name__}({self.mapping})>"

    def __contains__(self, key: str) -> bool:
        return key in self._columns

    def __delitem__(self, key) -> None:
        value = self[key]
        del self.mapping[key]
        self.pop(value, None)

    def __setitem__(self, key, value):
        self.mapping[key] = value
        if not key in self._columns:
            self._columns.append(key)

    def __getitem__(self, key: Union[str, int]) -> Any:
        """
        Sequence-like operators
        """
        try:
            return self.mapping[key]
        except (KeyError, TypeError):
            return None

    def __getattr__(self, attr: str) -> Any:
        """
        Attributes for dict keys
        """
        try:
            return self.__getitem__(attr)
        except KeyError:
            raise KeyError(
                f"User Error: invalid field name {attr} on {self.mapping!r}"
            )
        except TypeError:
            raise TypeError(
                f"User Error: invalid attribute value on {self.mapping!r} for {attr}"
            )

    def __iter__(self) -> Iterator:
        for value in self.mapping:
            yield value
