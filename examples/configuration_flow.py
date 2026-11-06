from pathlib import Path
import sys

from ariadne._util import loads, dumps
from ariadne.configuration import ConfigurationStore


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".ariadne")
    config = loads(Path(__file__).with_name("configuration.json").read_text())
    store = ConfigurationStore(root)
    store.replace_configuration(config, expected_revision=0)
    snapshot = store.create_snapshot()
    print(dumps({"directory": str(root), "snapshot_id": snapshot.id, "resolved": snapshot.render_profile("coder", {
        "task": "Implement task search", "project_context": "Python and SQLite", "findings": "No previous findings"})}, pretty=True))


if __name__ == "__main__":
    main()
