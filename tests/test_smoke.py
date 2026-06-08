def test_imports_work():
    import hid  # noqa: F401
    assert True


def test_pyobjc_imports_available_on_darwin():
    import sys
    if sys.platform != "darwin":
        return  # macOS-only deps
    import Quartz  # noqa: F401
    import ApplicationServices  # noqa: F401
