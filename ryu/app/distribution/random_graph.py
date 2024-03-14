import networkx as nx
import random
import numpy as np


def random_graph(n, p, w):
    G0 = nx.erdos_renyi_graph(n, p)
    G = nx.Graph()  # 创建无向图
    for u, v in G0.edges():
        G.add_edge(u, v, weight=int(random.uniform(1, w)))
    for node in G0.nodes:
        if G0.degree(node) == 0:
            to = random.randint(0, n)
            while to == node:
                to = random.randint(0, n)
            G.add_edge(node, to, weight=int(random.uniform(1, w)))
    sub_graphs = list(nx.connected_components(G))
    if len(sub_graphs) != 1:
        for i in range(1, len(sub_graphs)):
            G.add_edge(next(iter(sub_graphs[i - 1])), next(iter(sub_graphs[i])), weight=int(random.uniform(1, w)))
    return G


def print_graph(G, show_weight=True):
    import matplotlib.pyplot as plt  # 导入 Matplotlib 工具包
    pos = nx.spring_layout(G, iterations=20)  # 用 FR算法排列节点
    nx.draw(G, pos, with_labels=True, alpha=0.5)
    if show_weight:
        labels = nx.get_edge_attributes(G, 'weight')
        nx.draw_networkx_edge_labels(G, pos, edge_labels=labels)
    plt.show()  # 显示图形


def print_graph_with_labels(G, labels):
    import matplotlib.pyplot as plt  # 导入 Matplotlib 工具包
    pos = nx.spring_layout(G, iterations=20)
    nx.draw(G, pos, with_labels=True, alpha=0.5)
    nx.draw_networkx_edge_labels(G, pos, edge_labels=labels)
    plt.show()


def demo_graph():
    A = np.array([
        [0, 39, 33, 15, 0, 0, 0, 0, 0],
        [39, 0, 0, 21, 0, 0, 46, 0, 0],
        [33, 0, 0, 0, 23, 0, 0, 0, 0],
        [15, 21, 0, 0, 40, 18, 71, 0, 0],
        [0, 0, 23, 40, 0, 0, 0, 29, 0],
        [0, 0, 0, 18, 0, 0, 0, 25, 25],
        [0, 46, 0, 71, 0, 0, 0, 0, 20],
        [0, 0, 0, 0, 29, 25, 0, 0, 45],
        [0, 0, 0, 0, 0, 25, 20, 45, 0],
    ])
    G = nx.from_numpy_array(A)
    return G


def demo_graph_kmb():
    A = np.array([
        [0, 10, 0, 0, 0, 0, 0, 0, 1],
        [0, 0, 8, 0, 0, 1, 0, 0, 0],
        [0, 0, 0, 9, 2, 0, 0, 0, 0],
        [0, 0, 0, 0, 2, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 1, 0, 0, 1],
        [0, 0, 0, 0, 0, 0, 1, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0.5, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0.5],
        [0, 0, 0, 0, 0, 0, 0, 0, 0],
    ])
    G = nx.from_numpy_array(A)
    return G


def gt_itm_ts(n: int):
    return gt_itm_example(f"graphs/ts{n}-0.alt")


def gt_itm_example(filename) -> nx.Graph:
    g = nx.Graph()
    with open(filename, "r") as f:
        flag = False
        for line in f.readlines():
            if not flag and line.startswith("EDGES"):
                flag = True
            elif flag:
                arr = line.split(' ')[:2]
                g.add_edge(int(arr[0]), int(arr[1]))
    return g


def gt_itm_r(n):
    if n == 100:
        return random_graph(100, .04, 1)
    elif n == 175:
        return random_graph(175, .02, 1)
    elif n == 250:
        return random_graph(250, .01, 1)
    elif n == 325:
        return random_graph(325, .01, 1)
    elif n == 400:
        return random_graph(400, .009, 1)
    else:
        return None


if __name__ == '__main__':
    print(gt_itm_ts(100))
    print(gt_itm_ts(175))
    print(gt_itm_ts(250))
    print(gt_itm_ts(325))
    print(gt_itm_ts(400))
