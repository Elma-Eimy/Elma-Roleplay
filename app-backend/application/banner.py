"""Local and LAN addresses displayed after application startup."""

from core.utils import get_local_ips


def print_startup_banner():
    local_ips = get_local_ips()

    def banner_print(msg=""):
        print(msg, flush=True)

    banner_print("\n" + "=" * 80)
    banner_print(" [OK] AI Roleplay Backend 已成功启动并就绪！")
    banner_print("=" * 80)
    banner_print(" 1. 本地开发调试地址 (当前机器访问):")
    banner_print("    -> http://127.0.0.1:8000")
    banner_print("\n 2. 局域网访问地址 (同一 Wi-Fi 或局域网内的手机/其他设备访问):")
    if local_ips:
        for ip in local_ips:
            banner_print(f"    -> http://{ip}:8000")
        banner_print("\n * 使用提示：")
        banner_print("    - 如果在手机 App/小程序中连接此后端，请在设置中输入上述任意一个局域网地址。")
        banner_print("    - 确保手机与运行本后端的电脑连接在【同一个 Wi-Fi】下。")
        banner_print("    - 若连接失败，请检查电脑防火墙是否允许 8000 端口入站流量。")
    else:
        banner_print("      [!] 未检测到活跃的局域网 IP，请检查您的网线/无线连接。")
    banner_print("=" * 80 + "\n")
