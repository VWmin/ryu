import random
import networkx as nx

from ryu.app.distribution.route import pll_weighted
from math import inf

from ryu.app.distribution.route.util import PriorityQueue


def inc_pll_w(g: nx.Graph, l0, a, b):
    to_resume = list(l0[a].keys() | l0[b].keys())
    to_resume.sort()
    d = pll_weighted.query_distance
    for v in to_resume:
        if v in l0[a]:
            resume_pbfs(g, v, b, d(l0, v, a) + g[a][b]['weight'], l0)
        if v in l0[b]:
            resume_pbfs(g, v, a, d(l0, v, b) + g[a][b]['weight'], l0)
    return l0


def resume_pbfs(g: nx.Graph, root, u, d, l0):
    que = PriorityQueue()
    que.push((d, u))
    while que.size() != 0:
        d, u = que.pop()
        if d < prefixal_query(l0, root, u, root):
            l0[u][root] = d
            for v in g.neighbors(u):
                que.push((d + g[u][v]['weight'], v))


def prefixal_query(labels, u, v, k):
    distance = inf
    common = labels[u].keys() & labels[v].keys()
    for landmark in common:
        if landmark <= k:
            distance = min(distance, labels[u][landmark] + labels[v][landmark])
    return distance


def verify(g, correct_l, test_l):
    from pll_weighted import query_distance as d
    for u in g.nodes:
        for v in g.nodes:
            excepted = d(correct_l, u, v)
            got = d(test_l, u, v)
            # sp = nx.single_source_dijkstra(g1, u, v)
            if excepted != got:
                print(f"in {u, v}, excepted: {excepted}, got: {got}")
