#include <tins/tins.h>

#include <cassert>
#include <iostream>
#include <string>
#include <chrono>
#include <vector>
#include <algorithm>
#include <ctime>
#include <cstring>
#include <sstream>
#include <bitset>
#include <iomanip>
#include <unordered_map>


#include <unistd.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <getopt.h>

using namespace Tins;


using payload_type = std::vector<uint8_t>;

static payload_type get_nowtime() {
    auto milliseconds_since_epoch =
    std::chrono::system_clock::now().time_since_epoch() /
    std::chrono::microseconds(1);
    payload_type vec;
    while (milliseconds_since_epoch) {
        uint8_t t = milliseconds_since_epoch % 10;
        vec.push_back(t);
        milliseconds_since_epoch /= 10;
    }
    reverse(vec.begin(), vec.end());
    return vec;
}

std::string ipv4MulticastToMac(const std::string& ipv4Multicast) {
    // 将IPv4组播地址转换为二进制字符串
    std::istringstream iss(ipv4Multicast);
    char delimiter;
    int octet;
    std::string binaryString;

    while (iss >> octet) {
        binaryString += std::bitset<8>(octet).to_string();
        iss >> delimiter; // Read and discard the delimiter ('.' in this case)
    }

    // 取IPv4组播地址的最低23位
    std::string lowest23Bits = binaryString.substr(9, 23);

    // 构建MAC地址
    std::stringstream macStream;
    macStream << "01:00:5E:";
    macStream << std::hex << std::setw(2) << std::setfill('0') << std::stoi(lowest23Bits.substr(0, 2), nullptr, 2);
    macStream << ":" << std::hex << std::setw(2) << std::setfill('0') << std::stoi(lowest23Bits.substr(2, 2), nullptr, 2);
    macStream << ":" << std::hex << std::setw(2) << std::setfill('0') << std::stoi(lowest23Bits.substr(4, 2), nullptr, 2);

    return macStream.str();
}

static EthernetII getEthernetII(const std::string& dst_ip_ = "10.0.0.2", const std::string& dst_mac_ = "00:00:00:00:00:02",
            const std::string& src_ip_ = "10.0.0.1", const std::string& src_mac_ = "00:00:00:00:00:01",
            const int& sport_ = 12345, const int& dport_ = 12345) {
    return EthernetII(dst_mac_, src_mac_) /
        IP(dst_ip_, src_ip_) /
        UDP(dport_, sport_) /
        RawPDU(get_nowtime());
}




int main(int argc, char **argv) {
    srand(unsigned(time(NULL)));
    std::string dst_ip = "";
    std::string dst_mac = "";
    int ch;
    while ((ch = getopt(argc, argv, "i:")) != -1) {
        switch (ch) {
            case 'i':
                dst_ip = std::string(optarg);
                break;
        }
    }
    dst_mac = ipv4MulticastToMac(dst_ip);
    std::cout << "dest_ip: " << dst_ip << "\n";
    std::cout << "dest_mac: " << dst_mac << "\n\n";


    auto interface_vec = NetworkInterface::all();
    NetworkInterface dev;
    bool flag = false;
    for (auto &ele : interface_vec) {
        if (!ele.is_loopback() && ele.is_up()) {
            dev = ele;
            flag = true;
            break;
        }
    }
    if (!flag) {
        std::cerr << "Can't find a interface.\n";
        exit(1);
    }


    #ifdef LOCAL
        NetworkInterface::Info info = dev.addresses();
        std::cout << "=====================================\n"
                  << "\tdevice name: " << dev.name() << "\n"
                  << "\tdevice ip:   " << info.ip_addr << "\n"
                  << "=====================================\n";

    #endif
    PacketSender sender;

    // 每轮的发包数
    const int MAX_NUM = 10;

    auto src_ip = info.ip_addr.to_string();
    auto src_mac = info.hw_addr.to_string();

    for (int send_num = 0; send_num < MAX_NUM; ++send_num) {
        auto packet_to_send = getEthernetII(dst_ip, dst_mac, src_ip, src_mac);
        sender.send(packet_to_send, dev);
        std::cout << "send packet number "<< send_num << "\n";
//        usleep(500);
        usleep(800000);
//        sleep(1);
    }

    return 0;
}