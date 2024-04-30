import math
import re
from collections import defaultdict
from datetime import datetime

import numpy as np
import matplotlib.pyplot as plt
import networkx as nx
import smallestenclosingcircle


class Position:
    def __init__(self, lat, lon, dt, cid):
        self.lat = lat
        self.lon = lon
        self.dt = dt
        self.cid = cid

    def set_dt(self, dt):
        self.dt = dt

    def __str__(self):
        return f"({self.lat}, {self.lon})"


def str2datetime(s):
    # 解析字符串，注意时区部分需要特别处理
    dt = datetime.strptime(s[:-3], "%Y-%m-%d %H:%M:%S.%f")
    return dt


def str2position(s):
    # 使用正则表达式匹配所有数字（包括小数点和负号）
    pattern = r"[-+]?\d*\.\d+|\d+"
    # 查找所有匹配项
    matches = re.findall(pattern, s)
    if len(matches) == 2:
        # 将提取的字符串转换为浮点数
        lat, lon = map(float, matches)
        return lat, lon
    else:
        return None  # 如果没有找到两个匹配项，返回None


def haversine(lat1, lon1, lat2, lon2):
    # 将角度转换为弧度
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    # 纬度和经度差
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    # 哈弗赛因公式
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    # 地球平均半径, 千米
    r = 6371

    # 计算距离, 米
    distance = c * r * 1000

    return distance


def read_cab_data():
    # 文件路径
    file_path = 'taxi_february.txt'

    # 初始化一个列表来存储行
    lines = []

    # 打开文件
    with open(file_path, 'r') as file:
        # 遍历每一行
        for i in range(290000):
            line = file.readline()
            # 如果读取到文件末尾，readline 会返回空字符串
            if not line:
                break
            lines.append(line)

    cab_data = []
    for line in lines:
        data = line.split(';')
        driver_id = int(data[0])
        try:
            dt = str2datetime(data[1])
            lat, lon = str2position(data[2])
            cab_data.append(Position(lat, lon, dt, driver_id))
        except ValueError:
            continue

    return cab_data


def sec():
    cab_data = read_cab_data()
    cab_to_position = {}
    i, j = 0, 0
    for j in range(0, 100):
        position = cab_data[j]
        cab_to_position[position.cid] = position

    min_x, min_y, min_r, cur_n, cur_i, cur_j = 0, 0, 0x7fffffff, 0, 0, 0
    while j < 280000:
        points = [(position.lat, position.lon) for position in cab_to_position.values()]
        x, y, r = smallestenclosingcircle.make_circle(points)
        if r < min_r:
            min_x, min_y, min_r, cur_n, cur_i, cur_j = x, y, r, len(cab_to_position), i, j
            print(min_x, min_y, min_r, cur_n)

        to_remove = cab_data[i]
        if to_remove.dt == cab_to_position[to_remove.cid].dt:
            del cab_to_position[to_remove.cid]
        i += 1
        j += 1
        to_add = cab_data[j]
        cab_to_position[to_add.cid] = to_add

    print("final >>> ")
    print(min_x, min_y, min_r, cur_n, cur_i, cur_j)
    return min_x, min_y, min_r, cur_n, cur_i, cur_j


def plt_trace(trace):
    # 为每个唯一的 id 生成一个颜色
    colors = plt.colormaps.get_cmap('tab20')

    # 绘制轨迹
    fig, ax = plt.subplots()
    for idx, (cid, points) in enumerate(trace.items()):
        lats, lons = zip(*points)
        ax.plot(lons, lats, marker='o', linestyle='-', markersize=5, label=f'ID {cid}', color=colors(idx))

    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.set_title('Trajectory by ID')
    ax.legend(title='ID')
    plt.show()


def plt_position(data):
    # data = [
    #     (1, 41.9057, 12.4802),
    #     (2, 41.9060, 12.4805),
    #     (3, 41.9058, 12.4803),
    #     (4, 41.9061, 12.4806)
    # ]
    # 使用tab20颜色映射来为每个id分配颜色
    colors = plt.colormaps.get_cmap('tab20')

    # 创建图和轴
    fig, ax = plt.subplots()

    # 绘制每个点
    for idx, (cid, lat, lon) in enumerate(data):
        ax.scatter(lon, lat, color=colors(idx), label=f'ID {cid}', s=100)  # s是点的大小

    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.set_title('Scatter Plot of Locations by ID')
    ax.legend(title='ID')
    plt.show()


def plt_link(data, limit):
    # 使用tab20颜色映射来为每个id分配颜色
    colors = plt.colormaps.get_cmap('tab20')

    # 创建图和轴
    fig, ax = plt.subplots()

    # 绘制点
    for idx, (cid, lat, lon) in enumerate(data):
        ax.scatter(lon, lat, color=colors(idx), label=f'ID {cid}', s=100)

    # 连接距离小于limit的点
    for i in range(len(data)):
        for j in range(i + 1, len(data)):
            id1, lat1, lon1 = data[i]
            id2, lat2, lon2 = data[j]
            if haversine(lat1, lon1, lat2, lon2) < limit:
                ax.plot([lon1, lon2], [lat1, lat2], 'k--')  # 使用虚线连接

    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.set_title(f'Connected Points with Distance < {limit}m')
    ax.legend(title='ID')
    plt.show()


def gen_g(data, limit, cid_to_node):
    # 创建一个空的图对象
    G = nx.Graph()

    # 添加节点
    for cid, lat, lon in data:
        G.add_node(cid_to_node[cid], pos=(lon, lat), cid=cid)

    # 添加边，仅当两点间距离小于1000米时
    for i in range(len(data)):
        for j in range(i + 1, len(data)):
            id1, lat1, lon1 = data[i]
            id2, lat2, lon2 = data[j]
            if haversine(lat1, lon1, lat2, lon2) < limit:
                G.add_edge(cid_to_node[id1], cid_to_node[id2])

    # 使用networkx绘制图
    # pos = nx.get_node_attributes(G, 'pos')
    # nx.draw(G, pos, with_labels=True, node_color='skyblue', edge_color='gray')
    # plt.title('Network Graph Based on Connectivity')
    # plt.show()
    return G


def query_trace(cab_data, dt: datetime, cid_to_node, limit) -> nx.Graph:
    trace = {}
    for position in cab_data:
        if position.cid in cid_to_node and position.dt < dt:
            trace[position.cid] = (position.lat, position.lon)
    return gen_g([(k, v[0], v[1]) for k, v in trace.items()], limit, cid_to_node)


def main():
    cab_data = read_cab_data()
    # target_cid = [2, 105, 260, 59, 257, 351, 193, 361, 331, 104, 80, 228, 232, 53, 234, 259]
    target_cid = [2, 59, 104, 193, 234, 257, 259, 260]
    cid_to_node = {2: 1, 59: 2, 104: 3, 193: 4, 234: 5, 257: 6, 259: 7, 260: 8}
    trace = defaultdict(list)

    time_slice = [datetime(year=2014, month=2, day=1, hour=3, minute=0, second=0),
                  datetime(year=2014, month=2, day=1, hour=4, minute=0, second=0),
                  datetime(year=2014, month=2, day=1, hour=5, minute=0, second=0), ]

    trace_slice1, trace_slice2, trace_slice3 = {}, {}, {}

    for i in range(22395, 34495):
        position = cab_data[i]
        if position.cid in target_cid:
            trace[position.cid].append((position.lat, position.lon))
            if position.dt < time_slice[0]:
                trace_slice1[position.cid] = (position.lat, position.lon)
            if position.dt < time_slice[1]:
                trace_slice2[position.cid] = (position.lat, position.lon)
            if position.dt < time_slice[2]:
                trace_slice3[position.cid] = (position.lat, position.lon)

    # plt_position([(k, v[0], v[1]) for k, v in trace_slice1.items()])
    # plt_position([(k, v[0], v[1]) for k, v in trace_slice2.items()])
    # plt_position([(k, v[0], v[1]) for k, v in trace_slice3.items()])
    limit = 3000
    g1 = gen_g([(k, v[0], v[1]) for k, v in trace_slice1.items()], limit, cid_to_node)
    # g2 = gen_g([(k, v[0], v[1]) for k, v in trace_slice2.items()], limit)
    g3 = gen_g([(k, v[0], v[1]) for k, v in trace_slice3.items()], limit, cid_to_node)

    cur_links = set(g1.edges)
    next_links = set(g3.edges)
    link_down_set = cur_links - next_links  # link down
    link_up_set = next_links - cur_links  # link up
    cur_links = next_links


    return g1


if __name__ == '__main__':
    main()
    # 2014-02-01 02:18:28.446326 2014-02-01 05:17:37.110420 for i in range(22395, 34495):
    # 41.92086969642 12.47414054486365 0.05441089086791257 16 27396 27495
    """"
    2 41.8905909264276, 12.494096511218
    105 41.8908407028144, 12.478980310202
    260 41.9002912354058, 12.4841768047883
    59 41.9119362177077, 12.497919746763
    257 41.900432514011, 12.5052757468754
    351 41.8967097650626, 12.4822073543653
    193 41.8924779871585, 12.5122609801676
    361 41.9454436702654, 12.4692896381021
    331 41.9103505695239, 12.420756155625
    104 41.9232848344521, 12.478553458322
    80 41.8967887686039, 12.4728235931388
    228 41.9060719021486, 12.4593067849357
    232 41.9294543621651, 12.4461558413991
    53 41.9313888233161, 12.5275249341023
    234 41.8800710211048, 12.4667918470993
    259 41.9095554242119, 12.5018832793768
    """
