import socket

def get_local_ips():
    """
    获取当前主机在局域网中的所有活跃 IPv4 地址。
    通过 UDP 路由选择探测与主机名解析相结合，保证在不同系统与网络环境下的准确性。
    """
    ips = set()
    
    # 1. 尝试通过路由查询获取主要出网网卡的局域网 IP (最准确)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 这里使用一个通用的公网 IP（并不实际建立连接或发送数据），让系统路由表自动选择合适的出口网卡
        s.connect(("8.8.8.8", 80))
        primary_ip = s.getsockname()[0]
        s.close()
        if primary_ip and not primary_ip.startswith("127."):
            ips.add(primary_ip)
    except Exception:
        pass
    
    # 2. 备用方案：获取主机名对应的所有 IPv4 地址，作为多网卡/多虚拟网卡环境下的补充
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            # 过滤回环地址与未配置成功的链路本地地址
            if not ip.startswith("127.") and not ip.startswith("169.254"):
                ips.add(ip)
    except Exception:
        pass
    
    return sorted(list(ips))
