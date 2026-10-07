import app


# Keeps pytest from exiting with "no tests collected" until the service has real tests.
def test_package_imports():
    assert app.__doc__
