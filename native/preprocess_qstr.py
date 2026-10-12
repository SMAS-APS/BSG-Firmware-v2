"""Equivalente portabile della pipeline cat | sed | gcc -E | sed di MicroPython."""
import re
import subprocess
import sys
from pathlib import Path
from run_qstr import ResponsePopen


def preprocess(output, compiler, headers, flags):
    source = "\n".join(Path(path).read_text(encoding="utf-8") for path in headers)
    source = re.sub(r"^Q\(.*\)", lambda match: '"' + match.group(0) + '"', source, flags=re.M)
    with ResponsePopen([compiler, "-E", *flags, "-"], stdin=subprocess.PIPE,
                       text=True, encoding="utf-8", stdout=subprocess.PIPE) as process:
        stdout, _ = process.communicate(source)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, compiler)
    text = re.sub(r'^"(Q\(.*\))"', r"\1", stdout, flags=re.M)
    Path(output).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] == "--args-file":
        sys.argv = [sys.argv[0]] + Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
    separator = sys.argv.index("--")
    preprocess(sys.argv[1], sys.argv[2], sys.argv[3:separator], sys.argv[separator + 1:])
