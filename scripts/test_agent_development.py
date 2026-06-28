"""Legacy Plane integration smoke script.

The Plane adapter was removed from the current source tree. Keep this script as
a non-failing placeholder so pytest collection stays clean and users get a
clear message if they execute it directly.
"""


def run_test():
    print("Plane integration is not available in this refactored work-item build.")
    print("Use scripts/test_sqlite_db.py for the local SQLite work-item store smoke test.")


if __name__ == "__main__":
    run_test()
