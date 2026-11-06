"""python -m cavemap render|dd SPEC [options]"""
import sys

from . import dd, render


def main():
    cmds = {"render": render.main, "dd": dd.main}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("usage: python -m cavemap {render,dd} SPEC [options]  (--help after the command for options)")
        return 2
    return cmds[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
