#!/usr/bin/env python3
import sys
from application import AppUpdater

if __name__ == "__main__":
    app = AppUpdater()
    sys.exit(app.run(sys.argv))
