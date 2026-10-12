"""Esegue gli strumenti QSTR con file di argomenti, evitando i limiti Windows."""
import os
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path


class ResponsePopen(subprocess.Popen):
    def __init__(self, command, **kwargs):
        self.response = None
        if os.name == "nt":
            handle, name = tempfile.mkstemp(prefix="bsg-qstr-", suffix=".rsp")
            self.response = Path(name)
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                for arg in command[1:]:
                    stream.write('"' + str(arg).replace("\\", "\\\\").replace('"', '\\"') + '"\n')
            command = [command[0], "@" + str(self.response)]
        try:
            super().__init__(command, **kwargs)
        except BaseException:
            if self.response:
                self.response.unlink(missing_ok=True)
            raise

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            if self.response:
                self.response.unlink(missing_ok=True)


if __name__ == "__main__":
    script, arguments = sys.argv[1:]
    sys.argv = [script] + Path(arguments).read_text(encoding="utf-8").splitlines()
    subprocess.Popen = ResponsePopen
    runpy.run_path(script, run_name="__main__")
