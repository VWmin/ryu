#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

from ryu.cmd import manager
from prepare1_graph_info import GraphInfo


def main():
    sys.argv.append('/home/fwy/ryu/ryu/app/distribution/controller.py')
    sys.argv.append('/home/fwy/ryu/ryu/app/flow_manager/flowmanager.py')
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
