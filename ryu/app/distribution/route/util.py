import heapq
import random

import networkx as nx


class PriorityQueue:
    def __init__(self):
        self.container = []

    def push(self, item):
        heapq.heappush(self.container, item)

    def pop(self):
        return heapq.heappop(self.container)

    def size(self):
        return len(self.container)


def verify_labels(g: nx.Graph, correct_l, test_l, use_sp=False):
    from pll_weighted import query_distance as d
    for u in g.nodes:
        for v in g.nodes:
            excepted = nx.single_source_dijkstra(g, u, v)[0] if use_sp else d(correct_l, u, v)
            got = d(test_l, u, v)
            if excepted != got:
                print(f"in {u, v}, excepted: {excepted}, got: {got}")


def random_s_with_number(total, number):
    ret = set()
    while len(ret) != number:
        ret.add(random.randint(0, total - 1))
    return list(ret)


def random_s2r_with_number(total, number, S):
    ret = {}
    for s in S:
        ret[s] = set()
        while len(ret[s]) != number:
            t = random.randint(0, total - 1)
            if t == s:
                continue
            ret[s].add(t)
    return ret


def random_d_with_range(S, lo, hi):
    D = {}
    for s in S:
        D[s] = random.randint(lo, hi)
    return D


def random_number_but_not_in(lo, hi, exclude):
    t = random.randint(lo, hi)
    while t in exclude:
        t = random.randint(lo, hi)
    return t


def random_s_from_graph(g: nx.Graph, number):
    ret = set()
    nodes = list(g.nodes)
    while len(ret) != number:
        t = random.choice(nodes)
        ret.add(t)
    return ret


def random_s2r_from_graph(g: nx.Graph, number, src_set):
    ret = {}
    nodes = list(g.nodes)
    for s in src_set:
        ret[s] = set()
        while len(ret[s]) != number:
            t = random.choice(nodes)
            if t == s:
                continue
            ret[s].add(t)
    return ret


def add_attr_with_random_value(g, name, lo, hi):
    for u, v in g.edges:
        g[u][v][name] = random.randint(lo, hi)
