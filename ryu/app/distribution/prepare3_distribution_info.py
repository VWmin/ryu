import json
import pickle

import cherrypy
import requests

from prepare1_graph_info import *
from ryu.app.distribution.route import heat_degree_matrix
from ryu.topology import switches


def _get_exp_info() -> GraphInfo:
    response = requests.get("http://localhost:9000/exp_info")
    return pickle.loads(response.content)


def _get_net_switches():
    response = requests.get("http://localhost:9001/switches")
    return pickle.loads(response.content)


# [(src_name, src_port_name, dst_name, dst_port_name), ...]
def _get_net_links():
    response = requests.get("http://localhost:9001/links")
    return pickle.loads(response.content)


class DistributionInfo:
    def __init__(self, graph_info: GraphInfo):
        self.graph_info = graph_info

        # route
        self.network = self.graph_info.graph
        self.network.add_node(0)  # dummy node
        self.instance = heat_degree_matrix.HeatDegreeModel(self.network, graph_info.D, graph_info.B, graph_info.S2R)
        self.routing_trees = self.instance.routing_trees
        self.src_related_cid = {s: set() for s in graph_info.S}

        for src, routing_tree in self.routing_trees.items():
            for node in routing_tree:
                self.src_related_cid[src].add(self.graph_info.sw_to_cid[node])

        # topo
        self.online_cid = set()
        self.online_swes = set()
        self.swes = []
        self.swes_inter_links = []

        for sw in _get_net_switches():
            dpid = sw["dpid"]
            sw_info = {"dpid": dpid, "ports": []}
            for port in sw["ports"]:
                port_no = switches.port_no_to_str(int(port["name"].split('eth')[-1]))
                port_info = {"dpid": dpid, "port_no": port_no, "hw_addr": port["mac"], "name": port["name"]}
                sw_info["ports"].append(port_info)
            self.swes.append(sw_info)

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

    def controller_enter(self, cid):
        if cid == 0:
            return
        if cid not in self.online_cid:
            self.online_cid.add(cid)
            for dpid in self.graph_info.cid_to_swes[cid]:
                self.online_swes.add(dpid)
            print(f"{cid} enter, now: {self.online_cid}")

    def controller_leave(self, cid):
        if cid == 0:
            return
        if cid in self.online_cid:
            self.online_cid.remove(cid)
            for dpid in self.graph_info.cid_to_swes[cid]:
                self.online_swes.remove(dpid)
            print(f"{cid} leave, now: {self.online_cid}")

    def switches(self):
        swes = []
        for sw in self.swes:
            if int(sw["dpid"]) in self.online_swes:
                swes.append(sw)
        return swes

    def links(self):
        links = []
        for link in self.swes_inter_links:
            if int(link["src"]["dpid"]) in self.online_swes and int(link["dst"]["dpid"]) in self.online_swes:
                links.append(link)
        return links

    def all_links(self):
        return self.swes_inter_links

    def latest_routing_trees(self, cid):
        if cid == 0:
            return None
        trees = []
        for src in self.src_related_cid:
            if cid in self.src_related_cid[src]:
                trees.append(self.routing_trees[src])
                self.src_related_cid[src].remove(cid)
        return trees, self.graph_info.multicast_info


class DistributionServer:
    def __init__(self, info: DistributionInfo):
        self.info = info

    @cherrypy.expose
    def links(self):
        return json.dumps(self.info.swes_inter_links)

    @cherrypy.expose
    def enter(self, cid=0):
        cid = int(cid)
        self.info.controller_enter(cid)

    @cherrypy.expose
    def leave(self, cid=0):
        cid = int(cid)
        self.info.controller_leave(cid)

    @cherrypy.expose
    def switches(self):
        return json.dumps(self.info.switches())

    @cherrypy.expose
    def links(self):
        return json.dumps(self.info.links())

    @cherrypy.expose
    def all_links(self):
        return pickle.dumps(self.info.all_links())

    @cherrypy.expose
    def trees(self, cid=0):
        return pickle.dumps(self.info.latest_routing_trees(int(cid)))


if __name__ == '__main__':
    gi = _get_exp_info()
    di = DistributionInfo(gi)
    cherrypy.config.update({'server.socket_port': 9002})
    cherrypy.quickstart(DistributionServer(di))
