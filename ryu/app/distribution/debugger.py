#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

from ryu.cmd import manager


def main():
    sys.argv.append('/home/fwy/ryu/ryu/app/distribution/controller_dds.py')
    # sys.argv.append('--verbose')
    sys.argv.append('--enable-debugger')
    sys.argv.append('--observe-links')
    sys.argv.append('--wsapi-port')
    sys.argv.append('8000')
    sys.argv.append('--controller-id')
    sys.argv.append('1')
    manager.main()


if __name__ == '__main__':
    main()
