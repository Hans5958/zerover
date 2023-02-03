
import os
import sys
import re
from subprocess import check_output, CalledProcessError, STDOUT


def call(args):
    args = [unicode(a) for a in args]
    print(['$'] + args)
    ret = check_output(args, stderr=STDOUT)
    print(ret)
    return ret

def main():

    # chert render
    # on site, replace:
    # "\s*?/(?!/)[^>]+?"
    # incl: site/*
    # excl: site/css,site/js/
    for dname, dirs, files in os.walk("site"):
        for fname in files:
            fpath = os.path.join(dname, fname)
            if fpath.startswith(f'site{os.path.sep}css') or fpath.startswith(f'site{os.path.sep}js') or fpath.startswith(f'site{os.path.sep}img'):
                continue
            print(fpath)
            with open(fpath) as f:
                s = f.read()
            s = re.sub(r"[\"']\s*?(\/(?!\/|zerover/)[^>]+?)\s*?[\"']", r'"/zerover\1"', s)
            with open(fpath, "w") as f:
                f.write(s)

    return


if __name__ == '__main__':
    sys.exit(main() or 0)
