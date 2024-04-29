#!/bin/bash

if [ $# -ne 2 ]; then
    echo "Usage: $0 <listen_address> <hostname>"
    exit 1
fi

multicast_ip="$1"
hostname="$2"
outfile="${multicast_ip}-${hostname}"

ip route add 224.0.0.0/4 dev "${hostname}"-eth0

# 启动iperf服务器，指定监听地址
iperf -s -u -B "$multicast_ip" > "$outfile" 2>&1 &

# 等待一段时间（例如60秒）
sleep 120

# 结束iperf服务器进程
pkill iperf
