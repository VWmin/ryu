import json
import pickle
import random

import cherrypy
import networkx as nx
import requests

from prepare1_graph_info import GraphInfo
from ryu.topology import switches
from ryu.topology.switches import Link


def _get_exp_info() -> GraphInfo:
    response = requests.get("http://localhost:9000/exp_info")
    return pickle.loads(response.content)


# [(src_name, src_port_name, dst_name, dst_port_name), ...]
def _get_net_links():
    response = requests.get("http://localhost:9001/links")
    return pickle.loads(response.content)


class DistributionInfo:
    def __init__(self, graph: nx.Graph):
        self.graph = graph
        self.controller_number = 2
        self.cid_to_swes = {}
        self.sw_to_cid = {}
        self.swes_inter_links = []

        for node in self.graph.nodes:
            cid = random.randint(1, self.controller_number)
            self.cid_to_swes.setdefault(cid, [])
            self.cid_to_swes[cid].append(node)
            self.sw_to_cid[node] = cid

        for link in _get_net_links():
            src_name, src_port_name, src_port_mac, dst_name, dst_port_name, dst_port_mac = link
            if 'h' in src_name or 'h' in dst_name:
                continue
            src_dpid, src_port_no = int(src_name[1:]), int(src_port_name.split('eth')[-1])
            dst_dpid, dst_port_no = int(dst_name[1:]), int(dst_port_name.split('eth')[-1])
            src = {"dpid": switches.dpid_to_str(src_dpid), "port_no": switches.port_no_to_str(src_port_no), "hw_addr": src_port_mac, "name": src_name}
            dst = {"dpid": switches.dpid_to_str(dst_dpid), "port_no": switches.port_no_to_str(dst_port_no), "hw_addr": dst_port_mac, "name": dst_name}
            link = {"src": src, "dst": dst}
            link_rev = {"src": dst, "dst": src}
            self.swes_inter_links.append(link)
            self.swes_inter_links.append(link_rev)


class DistributionServer:
    def __init__(self, info: DistributionInfo):
        self.info = info

    @cherrypy.expose
    def links(self):
        return json.dumps(self.info.swes_inter_links)


if __name__ == '__main__':
    gi = _get_exp_info()
    di = DistributionInfo(gi.graph)
    cherrypy.config.update({'server.socket_port': 9002})
    cherrypy.quickstart(DistributionServer(di))
