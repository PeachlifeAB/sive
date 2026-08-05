from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sive")
except PackageNotFoundError:  # Source imported without an installed distribution.
    __version__ = "0+unknown"
