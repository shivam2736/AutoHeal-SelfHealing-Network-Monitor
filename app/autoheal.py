# autoheal.py
import time
from device import Device
from snmp_monitor import check_device_status
from remediation import reboot_device

# Define your devices here or load from config/file
devices = [
    Device(ip="192.168.1.10"),
    Device(ip="192.168.1.20", community="private"),
]

CHECK_INTERVAL = 60  # seconds

def main():
    while True:
        for device in devices:
            print(f"Checking device {device.name} ({device.ip})...")
            status, info = check_device_status(device)
            if status:
                print(f"Device {device.name} is UP. Uptime: {info}")
            else:
                print(f"Device {device.name} is DOWN or unreachable: {info}")
                print("Starting remediation...")
                reboot_device(device)
            print("-" * 40)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
