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
        # topo
        self.cid_to_swes = graph_info.cid_to_swes
        self.sw_to_cid = graph_info.sw_to_cid
        self.online_cid = set()
        self.online_swes = set()
        self.swes = []  # [dpid: str, ports: [...], ...]
        self.swes_inter_links = []  # [src: {dpid, port_no, hw_addr, name}, dst: {...}, ...]

        for sw in _get_net_switches():
            dpid = sw["dpid"]
            sw_info = {"dpid": dpid.lower(), "ports": []}
            for port in sw["ports"]:
                port_no = switches.port_no_to_str(int(port["name"].split('eth')[-1]))
                port_info = {"dpid": dpid.lower(), "port_no": port_no.lower(), "hw_addr": port["mac"], "name": port["name"]}
                sw_info["ports"].append(port_info)
            self.swes.append(sw_info)

        for link in _get_net_links():
            src_name, src_port_name, src_port_mac, dst_name, dst_port_name, dst_port_mac = link
            if 'h' in src_name or 'h' in dst_name:
                continue
            src_dpid, src_port_no = int(src_name[1:]), int(src_port_name.split('eth')[-1])
            dst_dpid, dst_port_no = int(dst_name[1:]), int(dst_port_name.split('eth')[-1])
            src = {"dpid": switches.dpid_to_str(src_dpid).lower(), "port_no": switches.port_no_to_str(src_port_no).lower(), "hw_addr": src_port_mac.lower(), "name": src_name}
            dst = {"dpid": switches.dpid_to_str(dst_dpid).lower(), "port_no": switches.port_no_to_str(dst_port_no).lower(), "hw_addr": dst_port_mac.lower(), "name": dst_name}
            link = {"src": src, "dst": dst}
            link_rev = {"src": dst, "dst": src}
            self.swes_inter_links.append(link)
            self.swes_inter_links.append(link_rev)

        # route
        self.network = graph_info.graph
        self.network.add_node(0)  # dummy node
        self.instance = heat_degree_matrix.HeatDegreeModel(self.network, graph_info.D, graph_info.B, graph_info.S2R)
        self.src_recvs = {src: list(graph_info.S2R[src]) for src in graph_info.S2R}
        self.multicast_info = graph_info.multicast_info
        self.routing_trees = None
        self.src_related_cid = None
        self.reset_route()

    # TOPO RELATED START

    def controller_enter(self, cid):
        if cid == 0:
            return
        if cid not in self.online_cid:
            self.online_cid.add(cid)
            for dpid in self.cid_to_swes[cid]:
                self.online_swes.add(dpid)
            print(f"{cid} enter, now: {self.online_cid}")

    def controller_leave(self, cid):
        if cid == 0:
            return
        if cid in self.online_cid:
            self.online_cid.remove(cid)
            for dpid in self.cid_to_swes[cid]:
                self.online_swes.remove(dpid)
            print(f"{cid} leave, now: {self.online_cid}")

    def switches(self):
        swes = []
        for sw in self.swes:
            if int(sw["dpid"], 16) in self.online_swes:
                swes.append(sw)
        return swes

    def links(self):
        links = []
        for link in self.swes_inter_links:
            if int(link["src"]["dpid"], 16) in self.online_swes and int(link["dst"]["dpid"], 16) in self.online_swes:
                links.append(link)
        return links

    def all_links(self):
        return self.swes_inter_links

    # TOPO RELATED END

    # ROUTE RELATED START

    def latest_trees_for_c_install(self, cid):
        if cid == 0:
            return None
        trees = {}
        for src in self.src_related_cid:
            if cid in self.src_related_cid[src]:
                trees[src] = self.routing_trees[src]
                self.src_related_cid[src].remove(cid)
        return trees, self.multicast_info  # FIXME

    def all_trees(self):
        trees = {}  # {[src -> {switches: [], links: []}], ...}
        tmp_dpid2sw = {int(sw["dpid"], 16): sw for sw in self.swes}
        tmp_dpid2link = {(int(link["src"]["dpid"], 16), int(link["dst"]["dpid"], 16)): link for link in self.swes_inter_links}
        for src, tree in self.routing_trees.items():
            swes = [tmp_dpid2sw[node] for node in tree.nodes]
            links = []
            for u, v in tree.edges:
                links.append(tmp_dpid2link[(u, v)])
                links.append(tmp_dpid2link[(v, u)])
            trees[src] = {"switches": swes, "links": links, "hosts": []}
        return trees

    def current_groups(self):
        return self.src_recvs

    def available_nodes(self):
        # ret: {available_src: [nodes], available_dst: [nodes]}
        cur_nodes = [int(sw["dpid"], 16) for sw in self.swes]
        available_src = []
        for n in cur_nodes:
            if n not in self.src_recvs:
                available_src.append(n)
        return {"available_src": available_src, "available_dst": cur_nodes}

    def group_add(self, src, dst):
        if src in self.src_recvs:
            return
        self.multicast_info.add_group(src)
        self.src_recvs[src] = dst
        b_limit = MulticastInfo.random_bandwidth_limit_for_s_set(set(self.src_recvs.keys()))
        d_limit = MulticastInfo.random_delay_limit_for_s_set(set(self.src_recvs.keys()))
        s2r = {s: set(self.src_recvs[s]) for s in self.src_recvs}
        self.instance = heat_degree_matrix.HeatDegreeModel(self.network, d_limit, b_limit, s2r)
        self.reset_route()

    def group_mod(self, src, dst):
        if src not in self.src_recvs:
            print("Group mod fail: source node not in exist multicast.")
            return
        if set(dst) == set(self.src_recvs[src]):
            print("Group mod fail: destination nodes not change.")
            return
        # for node in dst:
        #     if node not in self.src_recvs[src]:
        #         self.instance.add_recv(src, node)
        # for node in self.src_recvs[src]:
        #     if node not in dst:
        #         self.instance.remove_recv(src, node)
        # self.src_recvs[src] = dst
        # self.instance.update()
        # self.reset_route()
        self.src_recvs[src] = dst
        b_limit = MulticastInfo.random_bandwidth_limit_for_s_set(set(self.src_recvs.keys()))
        d_limit = MulticastInfo.random_delay_limit_for_s_set(set(self.src_recvs.keys()))
        s2r = {s: set(self.src_recvs[s]) for s in self.src_recvs}
        self.instance = heat_degree_matrix.HeatDegreeModel(self.network, d_limit, b_limit, s2r)
        self.reset_route()

    def reset_route(self):
        self.routing_trees = self.instance.routing_trees
        self.src_related_cid = {s: set() for s in self.src_recvs}

        for src, routing_tree in self.routing_trees.items():
            for node in routing_tree:
                self.src_related_cid[src].add(self.sw_to_cid[node])

    # ROUTE RELATED END


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
        return pickle.dumps(self.info.latest_trees_for_c_install(int(cid)))

    @cherrypy.expose
    def all_trees(self):
        return json.dumps(self.info.all_trees())

    @cherrypy.expose
    def current_groups(self):
        return json.dumps(self.info.current_groups())

    @cherrypy.expose
    def available_nodes(self):
        return json.dumps(self.info.available_nodes())

    @cherrypy.expose
    @cherrypy.tools.json_in()
    def group_add(self):
        data = cherrypy.request.json
        self.info.group_add(data["src"], data["dst"])
        return "Data received successfully."

    @cherrypy.expose
    @cherrypy.tools.json_in()
    def group_mod(self):
        data = cherrypy.request.json
        self.info.group_mod(data['src'], data['dst'])
        return "Data received successfully."


if __name__ == '__main__':
    gi = _get_exp_info()
    di = DistributionInfo(gi)
    cherrypy.config.update({'server.socket_host': "0.0.0.0", 'server.socket_port': 9002})
    cherrypy.quickstart(DistributionServer(di))
