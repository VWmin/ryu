import pickle
import json
import math
import random
import threading
import time
from datetime import datetime, timedelta

import networkx
import networkx as nx
import cherrypy
from matplotlib import pyplot as plt


class MulticastInfo:
    b_req_lo, b_req_hi = 1, 2
    d_req_lo, d_req_hi = 50, 100

    def __init__(self, s2r):
        self.s2r = s2r
        self.group_no = 1
        self.src_to_group_no = {}
        self.src_to_group_ip = {}
        for s in self.s2r:
            self.add_group(s)

    def add_group(self, src):
        self.src_to_group_no[src] = self.group_no
        self.src_to_group_ip[src] = f'224.0.1.{self.src_to_group_no[src]}'
        self.group_no += 1

    @staticmethod
    def random_bandwidth_limit_for_s_set(S):
        return MulticastInfo.random_b_with_range(S, MulticastInfo.b_req_lo, MulticastInfo.b_req_hi)

    @staticmethod
    def random_delay_limit_for_s_set(S):
        return MulticastInfo.random_d_with_range(S, MulticastInfo.d_req_lo, MulticastInfo.d_req_hi)

    @staticmethod
    def random_b_with_range(S, lo, hi):
        B = {}
        for s in S:
            B[s] = round(random.uniform(lo, hi), 1)
        return B

    @staticmethod
    def random_d_with_range(S, lo, hi):
        D = {}
        for s in S:
            D[s] = random.uniform(lo, hi)
        return D


class GraphInfo:
    def __init__(self, graph: nx.Graph):
        self.graph = graph

        b_lo, b_hi = 5, 10
        d_lo, d_hi = 1, 10

        random.seed(42)

        self.total_bw = set_random_bw(self.graph, "bandwidth", b_lo, b_hi)
        add_attr_with_random_value(self.graph, "weight", d_lo, d_hi)
        self.S = random_s_from_graph(self.graph, 1)
        self.S2R = random_s2r_from_graph(self.graph, 3, self.S)
        self.B = MulticastInfo.random_bandwidth_limit_for_s_set(self.S)
        self.D = MulticastInfo.random_delay_limit_for_s_set(self.S)

        self.stp = False

        print(f"src set is {self.S}")
        print(f"src to recv is {self.S2R}")
        print(f"total bw is {self.total_bw}")
        print(f"bw requirement is {self.B}")

        self.controller_number = 1
        self.cid_to_swes = {}
        self.sw_to_cid = {}

        for node in self.graph.nodes:
            cid = random.randint(1, self.controller_number)
            self.cid_to_swes.setdefault(cid, [])
            self.cid_to_swes[cid].append(node)
            self.sw_to_cid[node] = cid

        group_no = 1
        self.src_to_group_no = {}
        for s in self.S2R:
            self.src_to_group_no[s] = group_no
            group_no += 1

        self.multicast_info = MulticastInfo(self.S2R)

        output = {
            "s2r": {},
            "bw_requirement": self.B,
            "total_bw": self.total_bw,
            "src_to_group": self.src_to_group_no,
            "cid_to_swes": self.cid_to_swes,
        }
        for s in self.S2R:
            output["s2r"][s] = []
            for r in self.S2R[s]:
                output["s2r"][s].append(r)

        with open('ev_setting.json', 'w') as json_file:
            json.dump(output, json_file, indent=4)

    def src_to_group_ip(self, src):
        return f'224.0.1.{self.src_to_group_no[src]}'

    def add_random_r(self):
        s = random.choice(list(self.S))
        nodes = list(self.graph.nodes)
        r = random.choice(nodes)
        while r in self.S2R[s]:
            r = random.choice(nodes)
        self.S2R[s].add(r)
        print(f"add receiver {r}")

    def remove_random_r(self):
        s = random.choice(list(self.S))
        r = random.choice(list(self.S2R[s]))
        self.S2R[s].remove(r)
        print(f"remove receiver {r}")

    def inc_link_delay(self, u, v):
        self.graph[u][v]['weight'] = self.graph[u][v]['weight'] * 1.3
        print(f"inc edge {u, v} delay")

    def disable_link(self, u, v):
        self.graph[u][v]['weight'] = math.inf
        print(f"disable edge {u, v}")


def add_attr_with_random_value(g, name, lo, hi):
    for u, v in g.edges:
        g[u][v][name] = random.randint(lo, hi)


def set_random_bw(g, name, lo, hi):
    tot = 0
    for u, v in g.edges:
        bw = random.randint(lo, hi)
        tot += bw
        g[u][v][name] = bw
    return tot


def random_s_from_graph(g: nx.Graph, number):
    ret = set()
    nodes = list(g.nodes)
    while len(ret) != number:
        t = random.choice(nodes)
        ret.add(t)
    return ret


def random_s2r_from_graph(g: nx.Graph, number, src_set):
    ret = {}
    used = set()
    nodes = list(g.nodes)
    for s in src_set:
        ret[s] = set()
        used.add(s)
        while len(ret[s]) != number:
            t = random.choice(nodes)
            if t in used:
                continue
            ret[s].add(t)
            used.add(t)
    return ret


class GraphInfoServer:
    is_latest = False
    g = None
    def __init__(self, info):
        self.info = info

    @cherrypy.expose
    def exp_info(self):
        return pickle.dumps(self.info)

    @cherrypy.expose
    def latest_graph(self):
        if not GraphInfoServer.is_latest:
            return pickle.dumps((False, None))
        else:
            GraphInfoServer.is_latest = False
            return pickle.dumps((True, GraphInfoServer.g))

    @staticmethod
    def update_graph(start_dt, cid_to_node, limit, cab_data, pre_g):
        time.sleep(3)
        while True:
            start_dt = start_dt + timedelta(seconds=24)  # exp will cost 5min
            cur_g = read_data.query_trace(cab_data, start_dt, cid_to_node, limit)
            if not networkx.is_isomorphic(cur_g, pre_g):
                GraphInfoServer.is_latest = True
                GraphInfoServer.g = cur_g
                pre_g = cur_g
                # plt_g(g)
                print(f"graph updated at {start_dt}")
            time.sleep(3)


def plt_g(g):
    pos = nx.get_node_attributes(g, 'pos')
    nx.draw(g, pos, with_labels=True, node_color='skyblue', edge_color='gray')
    plt.title('Network Graph Based on Connectivity')
    plt.show()


if __name__ == "__main__":
    import read_data

    start_dt = datetime(year=2014, month=2, day=1, hour=3, minute=0, second=0)
    cid_to_node = {2: 1, 59: 2, 104: 3, 193: 4, 234: 5, 257: 6, 259: 7, 260: 8}
    limit = 3000
    cab_data = read_data.read_cab_data()[22395: 34495]

    g = read_data.query_trace(cab_data, start_dt, cid_to_node, limit)
    i = GraphInfo(g)
    plt_g(g)


    def runserver():
        cherrypy.config.update({'server.socket_host': "0.0.0.0", 'server.socket_port': 9000})
        cherrypy.quickstart(GraphInfoServer(i))


    t = threading.Thread(target=GraphInfoServer.update_graph, args=(start_dt, cid_to_node, limit, cab_data, g))
    t2 = threading.Thread(target=runserver)

    t.start()
    t2.start()
    t.join()
    t2.join()
