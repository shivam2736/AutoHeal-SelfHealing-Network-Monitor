# snmp_monitor.py
from pysnmp.hlapi import *

def snmp_get(ip, community, oid, port=161, timeout=1, retries=3):
    for attempt in range(retries):
        errorIndication, errorStatus, errorIndex, varBinds = next(
            getCmd(SnmpEngine(),
                   CommunityData(community, mpModel=0),
                   UdpTransportTarget((ip, port), timeout=timeout, retries=0),
                   ContextData(),
                   ObjectType(ObjectIdentity(oid)))
        )
        if errorIndication:
            if attempt == retries - 1:
                raise Exception(f"SNMP error: {errorIndication}")
        elif errorStatus:
            raise Exception(f"SNMP error: {errorStatus.prettyPrint()}")
        else:
            for varBind in varBinds:
                return varBind[1]
    raise Exception("SNMP get failed after retries")

def check_device_status(device):
    # Example OID for sysUpTime
    sys_uptime_oid = '1.3.6.1.2.1.1.3.0'
    try:
        uptime = snmp_get(device.ip, device.community, sys_uptime_oid)
        return True, uptime  # Device responding
    except Exception as e:
        return False, str(e)
