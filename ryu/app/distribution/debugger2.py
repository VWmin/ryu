#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

from ryu import cfg
from ryu.cmd import manager

cfg.CONF.register_cli_opts([cfg.IntOpt('controller-id', default=1, help='distribution controller id (default %s)' % 1), ])


def main():
    sys.argv.append('/home/fwy/Desktop/graph/distribution/controller.py')
    # sys.argv.append('--verbose')
    sys.argv.append('--enable-debugger')
    sys.argv.append('--observe-links')
    sys.argv.append('--ofp-tcp-listen-port')
    sys.argv.append('6634')
    sys.argv.append('--wsapi-port')
    sys.argv.append('8001')
    sys.argv.append('--controller-id')
    sys.argv.append('2')
    manager.main()


if __name__ == '__main__':
    main()
