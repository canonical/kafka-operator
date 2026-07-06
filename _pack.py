"""
Temporary workaround for `charmcraft pack` restrictions, ONLY for development purposes.

Please refer to DA-263 for more information.

FIXME: This should be removed once charmcraft supports git-driven build roots (ST-178).
"""


import os
import sys

Command = str


def _alternate_pack_script(charm_dir: str, *args) -> list[Command]:
    raw = rf"""
    mkdir -p build
    find build/ -iname *.charm -exec rm {{}} \;
    touch build/DEVMODE
    rsync -av {charm_dir}/ build/
    rsync -av common/ build/.common
    /bin/bash -c "cd build && charmcraft pack -v {' '.join(args)}"
    find build/ -iname *.charm -exec cp {{}} {charm_dir}/ \;
    """
    return [cmd.strip() for cmd in raw.split("\n") if cmd.strip()]


def _exec(cmd: str) -> int:
    print(f"Executing: {cmd}")
    return os.system(cmd)


def _exit(code: int, error: str = ""):
    print("Usage: _pack.py charm-dir [charmcraft pack args]")
    print(error)
    sys.exit(code)


if __name__ == "__main__":

    if len(sys.argv) < 2:
        _exit(1, "charm-dir should be provided.")

    charm_dir = sys.argv[1].rstrip("/")

    ret = 0
    if charm_dir in ["machine", "k8s"]:
        for cmd in _alternate_pack_script(charm_dir, *sys.argv[2:]):
            ret += _exec(cmd)
    else:
        cwd = os.getcwd()
        os.chdir(charm_dir)
        ret = _exec(f"charmcraft pack {' '.join(sys.argv[2:])}")
        os.chdir(cwd)

    sys.exit(ret)
