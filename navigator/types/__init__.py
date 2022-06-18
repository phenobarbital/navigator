class Singleton(type):
    """Singleton.

    Metaclass for Singleton instances.

    Returns:
        self: a singleton version of the class.
    """
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(
                Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

    def __new__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(
                Singleton, cls).__new__(cls, *args, **kwargs)
            setattr(cls, '__initialized', True)
        return cls._instances[cls]
