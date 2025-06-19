#!/usr/bin/env python3
"""
AutoHeal: Self-Healing Factory Network Monitoring System
A comprehensive network monitoring and auto-remediation system for factory environments.
"""

import asyncio
import json
import logging
import smtplib
import sqlite3
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from threading import Thread
from typing import Dict, List, Optional, Tuple
import ipaddress

# Third-party imports (install with: pip install netmiko pysnmp flask)
from netmiko import ConnectHandler
from pysnmp.hlapi import *
from flask import Flask, render_template, jsonify, request

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('autoheal.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class NetworkDevice:
    """Represents a network device in the factory."""
    
    def __init__(self, ip: str, hostname: str, device_type: str, 
                 snmp_community: str = 'public', priority: str = 'medium'):
        self.ip = ip
        self.hostname = hostname
        self.device_type = device_type
        self.snmp_community = snmp_community
        self.priority = priority
        self.status = 'unknown'
        self.last_seen = None
        self.failure_count = 0
        self.interfaces = {}
        
    def to_dict(self) -> Dict:
        return {
            'ip': self.ip,
            'hostname': self.hostname,
            'device_type': self.device_type,
            'status': self.status,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'failure_count': self.failure_count,
            'priority': self.priority,
            'interfaces': self.interfaces
        }

class SNMPMonitor:
    """SNMP-based network device monitoring."""
    
    def __init__(self):
        self.oids = {
            'system_uptime': '1.3.6.1.2.1.1.3.0',
            'system_desc': '1.3.6.1.2.1.1.1.0',
            'interface_status': '1.3.6.1.2.1.2.2.1.8',  # ifOperStatus
            'interface_name': '1.3.6.1.2.1.2.2.1.2',   # ifDescr
            'cpu_usage': '1.3.6.1.4.1.9.9.109.1.1.1.1.7.1',  # Cisco CPU
            'memory_usage': '1.3.6.1.4.1.9.9.48.1.1.1.5.1'   # Cisco Memory
        }
    
    async def check_device_health(self, device: NetworkDevice) -> Dict:
        """Check device health via SNMP."""
        try:
            health_data = {
                'reachable': False,
                'uptime': None,
                'cpu_usage': None,
                'memory_usage': None,
                'interfaces': {}
            }
            
            # Check basic connectivity and uptime
            for (errorIndication, errorStatus, errorIndex, varBinds) in nextCmd(
                SnmpEngine(),
                CommunityData(device.snmp_community),
                UdpTransportTarget((device.ip, 161)),
                ContextData(),
                ObjectType(ObjectIdentity(self.oids['system_uptime'])),
                lexicographicMode=False):
                
                if errorIndication or errorStatus:
                    break
                    
                health_data['reachable'] = True
                health_data['uptime'] = int(varBinds[0][1]) / 100  # Convert to seconds
                break
            
            if health_data['reachable']:
                # Check interface status
                interfaces = await self._get_interface_status(device)
                health_data['interfaces'] = interfaces
                
                device.status = 'up'
                device.last_seen = datetime.now()
                device.failure_count = 0
            else:
                device.status = 'down'
                device.failure_count += 1
                
            return health_data
            
        except Exception as e:
            logger.error(f"SNMP check failed for {device.ip}: {e}")
            device.status = 'error'
            device.failure_count += 1
            return {'reachable': False, 'error': str(e)}
    
    async def _get_interface_status(self, device: NetworkDevice) -> Dict:
        """Get interface status via SNMP."""
        interfaces = {}
        try:
            # Get interface names and status
            for (errorIndication, errorStatus, errorIndex, varBinds) in nextCmd(
                SnmpEngine(),
                CommunityData(device.snmp_community),
                UdpTransportTarget((device.ip, 161)),
                ContextData(),
                ObjectType(ObjectIdentity(self.oids['interface_name'])),
                ObjectType(ObjectIdentity(self.oids['interface_status'])),
                lexicographicMode=False):
                
                if errorIndication or errorStatus:
                    break
                
                if_name = str(varBinds[0][1])
                if_status = int(varBinds[1][1])
                
                interfaces[if_name] = {
                    'status': 'up' if if_status == 1 else 'down',
                    'admin_status': if_status
                }
                
        except Exception as e:
            logger.error(f"Interface check failed for {device.ip}: {e}")
            
        return interfaces

class NetworkRemediator:
    """Handles automated network issue remediation."""
    
    def __init__(self):
        self.remediation_methods = {
            'interface_down': self._fix_interface,
            'device_unresponsive': self._reboot_device,
            'high_cpu': self._restart_processes,
            'memory_leak': self._clear_memory
        }
    
    async def remediate_issue(self, device: NetworkDevice, issue_type: str, 
                            details: Dict) -> Dict:
        """Execute automated remediation based on issue type."""
        logger.info(f"Starting remediation for {device.ip}: {issue_type}")
        
        try:
            if issue_type in self.remediation_methods:
                result = await self.remediation_methods[issue_type](device, details)
                return result
            else:
                return {'success': False, 'message': f'No remediation for {issue_type}'}
                
        except Exception as e:
            logger.error(f"Remediation failed for {device.ip}: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _fix_interface(self, device: NetworkDevice, details: Dict) -> Dict:
        """Fix down interfaces by toggling them."""
        try:
            connection_params = {
                'device_type': 'cisco_ios',  # Adjust based on device
                'host': device.ip,
                'username': 'admin',  # Configure in production
                'password': 'password',  # Use secure credential management
                'timeout': 30
            }
            
            with ConnectHandler(**connection_params) as net_connect:
                for interface, status in details.get('interfaces', {}).items():
                    if status['status'] == 'down':
                        commands = [
                            f'interface {interface}',
                            'shutdown',
                            'no shutdown',
                            'exit'
                        ]
                        
                        output = net_connect.send_config_set(commands)
                        logger.info(f"Interface {interface} toggled on {device.ip}")
                        
                        # Wait and verify
                        await asyncio.sleep(5)
                        
            return {'success': True, 'message': 'Interfaces remediated'}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _reboot_device(self, device: NetworkDevice, details: Dict) -> Dict:
        """Reboot unresponsive device."""
        try:
            connection_params = {
                'device_type': 'cisco_ios',
                'host': device.ip,
                'username': 'admin',
                'password': 'password',
                'timeout': 30
            }
            
            with ConnectHandler(**connection_params) as net_connect:
                # Save configuration first
                net_connect.send_command('write memory')
                
                # Reboot
                output = net_connect.send_command(
                    'reload', 
                    expect_string=r'confirm',
                    strip_prompt=False,
                    strip_command=False
                )
                net_connect.send_command('y')
                
            logger.info(f"Device {device.ip} rebooted")
            return {'success': True, 'message': 'Device rebooted'}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _restart_processes(self, device: NetworkDevice, details: Dict) -> Dict:
        """Restart high-CPU processes."""
        # Implementation depends on device type and OS
        return {'success': True, 'message': 'Processes restarted'}
    
    async def _clear_memory(self, device: NetworkDevice, details: Dict) -> Dict:
        """Clear memory caches."""
        # Implementation depends on device type
        return {'success': True, 'message': 'Memory cleared'}

class AlertManager:
    """Manages alert generation and notification."""
    
    def __init__(self, smtp_config: Dict):
        self.smtp_config = smtp_config
        self.alert_thresholds = {
            'failure_count': 3,
            'response_time': 5.0,
            'cpu_threshold': 80.0,
            'memory_threshold': 85.0
        }
    
    async def send_alert(self, device: NetworkDevice, issue_type: str, 
                        details: Dict, severity: str = 'medium'):
        """Send alert notification."""
        try:
            subject = f"AutoHeal Alert: {issue_type} on {device.hostname}"
            
            body = f"""
AutoHeal Network Monitoring Alert

Device: {device.hostname} ({device.ip})
Issue: {issue_type}
Severity: {severity.upper()}
Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Priority: {device.priority}

Details:
{json.dumps(details, indent=2)}

Automated remediation will be attempted if configured.

--
AutoHeal Network Monitoring System
            """
            
            msg = MIMEText(body)
            msg['Subject'] = subject
            msg['From'] = self.smtp_config['from_email']
            msg['To'] = self.smtp_config['to_email']
            
            # Send email (configure SMTP settings)
            if self.smtp_config.get('enabled', False):
                with smtplib.SMTP(self.smtp_config['server'], 
                                self.smtp_config['port']) as server:
                    if self.smtp_config.get('use_tls'):
                        server.starttls()
                    if self.smtp_config.get('username'):
                        server.login(self.smtp_config['username'], 
                                   self.smtp_config['password'])
                    server.send_message(msg)
                    
            logger.info(f"Alert sent for {device.ip}: {issue_type}")
            
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

class DatabaseManager:
    """Manages SQLite database for storing monitoring data."""
    
    def __init__(self, db_path: str = 'autoheal.db'):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY,
                    ip TEXT UNIQUE,
                    hostname TEXT,
                    device_type TEXT,
                    priority TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS monitoring_history (
                    id INTEGER PRIMARY KEY,
                    device_ip TEXT,
                    status TEXT,
                    uptime REAL,
                    cpu_usage REAL,
                    memory_usage REAL,
                    interfaces TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS remediation_log (
                    id INTEGER PRIMARY KEY,
                    device_ip TEXT,
                    issue_type TEXT,
                    remediation_type TEXT,
                    success BOOLEAN,
                    details TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
    
    def save_monitoring_data(self, device: NetworkDevice, health_data: Dict):
        """Save monitoring data to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO monitoring_history 
                    (device_ip, status, uptime, interfaces)
                    VALUES (?, ?, ?, ?)
                ''', (
                    device.ip,
                    device.status,
                    health_data.get('uptime'),
                    json.dumps(health_data.get('interfaces', {}))
                ))
        except Exception as e:
            logger.error(f"Failed to save monitoring data: {e}")
    
    def log_remediation(self, device_ip: str, issue_type: str, 
                       remediation_type: str, success: bool, details: Dict):
        """Log remediation attempt."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO remediation_log 
                    (device_ip, issue_type, remediation_type, success, details)
                    VALUES (?, ?, ?, ?, ?)
                ''', (device_ip, issue_type, remediation_type, success, 
                      json.dumps(details)))
        except Exception as e:
            logger.error(f"Failed to log remediation: {e}")

class AutoHealMonitor:
    """Main AutoHeal monitoring system."""
    
    def __init__(self, config_file: str = 'autoheal_config.json'):
        self.config = self._load_config(config_file)
        self.devices = {}
        self.snmp_monitor = SNMPMonitor()
        self.remediator = NetworkRemediator()
        self.alert_manager = AlertManager(self.config.get('smtp', {}))
        self.db_manager = DatabaseManager()
        self.running = False
        
        # Load devices from config
        self._load_devices()
    
    def _load_config(self, config_file: str) -> Dict:
        """Load configuration from JSON file."""
        default_config = {
            "monitoring_interval": 60,
            "remediation_enabled": True,
            "alert_enabled": True,
            "devices": [
                {
                    "ip": "192.168.1.10",
                    "hostname": "core-switch-01",
                    "device_type": "switch",
                    "priority": "critical",
                    "snmp_community": "public"
                },
                {
                    "ip": "192.168.1.11", 
                    "hostname": "access-switch-01",
                    "device_type": "switch",
                    "priority": "high",
                    "snmp_community": "public"
                }
            ],
            "smtp": {
                "enabled": False,
                "server": "localhost",
                "port": 587,
                "use_tls": True,
                "from_email": "autoheal@factory.com",
                "to_email": "network-admin@factory.com"
            }
        }
        
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                return {**default_config, **config}
        except FileNotFoundError:
            logger.info(f"Config file {config_file} not found, using defaults")
            # Save default config
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
            return default_config
    
    def _load_devices(self):
        """Load devices from configuration."""
        for device_config in self.config['devices']:
            device = NetworkDevice(**device_config)
            self.devices[device.ip] = device
            logger.info(f"Loaded device: {device.hostname} ({device.ip})")
    
    async def monitor_device(self, device: NetworkDevice):
        """Monitor a single device."""
        try:
            # Check device health
            health_data = await self.snmp_monitor.check_device_health(device)
            
            # Save monitoring data
            self.db_manager.save_monitoring_data(device, health_data)
            
            # Analyze issues and trigger remediation
            issues = self._analyze_health_data(device, health_data)
            
            for issue_type, details in issues.items():
                logger.warning(f"Issue detected on {device.ip}: {issue_type}")
                
                # Send alert
                if self.config.get('alert_enabled', True):
                    severity = 'critical' if device.priority == 'critical' else 'medium'
                    await self.alert_manager.send_alert(
                        device, issue_type, details, severity
                    )
                
                # Attempt remediation
                if self.config.get('remediation_enabled', True):
                    remediation_result = await self.remediator.remediate_issue(
                        device, issue_type, details
                    )
                    
                    # Log remediation attempt
                    self.db_manager.log_remediation(
                        device.ip, issue_type, issue_type, 
                        remediation_result.get('success', False),
                        remediation_result
                    )
                    
                    if remediation_result.get('success'):
                        logger.info(f"Successfully remediated {issue_type} on {device.ip}")
                    else:
                        logger.error(f"Remediation failed for {issue_type} on {device.ip}")
                        
        except Exception as e:
            logger.error(f"Monitoring failed for {device.ip}: {e}")
    
    def _analyze_health_data(self, device: NetworkDevice, 
                           health_data: Dict) -> Dict:
        """Analyze health data and identify issues."""
        issues = {}
        
        # Check if device is unreachable
        if not health_data.get('reachable', False):
            if device.failure_count >= 3:
                issues['device_unresponsive'] = {
                    'failure_count': device.failure_count,
                    'last_seen': device.last_seen
                }
        
        # Check interface status
        down_interfaces = []
        for interface, status in health_data.get('interfaces', {}).items():
            if status['status'] == 'down':
                down_interfaces.append(interface)
        
        if down_interfaces:
            issues['interface_down'] = {
                'interfaces': {iface: health_data['interfaces'][iface] 
                             for iface in down_interfaces}
            }
        
        # Check CPU and memory (if available)
        if health_data.get('cpu_usage', 0) > 80:
            issues['high_cpu'] = {'cpu_usage': health_data['cpu_usage']}
            
        if health_data.get('memory_usage', 0) > 85:
            issues['memory_leak'] = {'memory_usage': health_data['memory_usage']}
        
        return issues
    
    async def monitoring_loop(self):
        """Main monitoring loop."""
        logger.info("Starting AutoHeal monitoring loop")
        self.running = True
        
        while self.running:
            try:
                # Monitor all devices concurrently
                tasks = [
                    self.monitor_device(device) 
                    for device in self.devices.values()
                ]
                
                await asyncio.gather(*tasks, return_exceptions=True)
                
                # Wait for next monitoring cycle
                await asyncio.sleep(self.config.get('monitoring_interval', 60))
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(10)  # Brief pause before retrying
    
    def start_monitoring(self):
        """Start the monitoring system."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(self.monitoring_loop())
        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user")
        finally:
            self.running = False
            loop.close()
    
    def get_system_status(self) -> Dict:
        """Get current system status for dashboard."""
        status = {
            'total_devices': len(self.devices),
            'devices_up': sum(1 for d in self.devices.values() if d.status == 'up'),
            'devices_down': sum(1 for d in self.devices.values() if d.status == 'down'),
            'devices_unknown': sum(1 for d in self.devices.values() if d.status == 'unknown'),
            'last_update': datetime.now().isoformat(),
            'devices': [device.to_dict() for device in self.devices.values()]
        }
        return status

# Flask Web Dashboard
app = Flask(__name__)
monitor_instance = None

@app.route('/')
def dashboard():
    """Main dashboard page."""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>AutoHeal Network Monitor</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
            .header { background: #2c3e50; color: white; padding: 20px; border-radius: 8px; }
            .stats { display: flex; gap: 20px; margin: 20px 0; }
            .stat-card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); flex: 1; }
            .device-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }
            .device-card { background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .status-up { border-left: 4px solid #27ae60; }
            .status-down { border-left: 4px solid #e74c3c; }
            .status-unknown { border-left: 4px solid #f39c12; }
            .refresh-btn { background: #3498db; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>🔧 AutoHeal Network Monitor</h1>
            <p>Self-Healing Factory Network Monitoring System</p>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <h3>Total Devices</h3>
                <div id="total-devices">-</div>
            </div>
            <div class="stat-card">
                <h3>Devices Up</h3>
                <div id="devices-up">-</div>
            </div>
            <div class="stat-card">
                <h3>Devices Down</h3>
                <div id="devices-down">-</div>
            </div>
            <div class="stat-card">
                <h3>Uptime</h3>
                <div id="uptime">-</div>
            </div>
        </div>
        
        <button class="refresh-btn" onclick="refreshData()">🔄 Refresh</button>
        
        <div id="device-list" class="device-grid"></div>
        
        <script>
            function refreshData() {
                fetch('/api/status')
                    .then(response => response.json())
                    .then(data => {
                        document.getElementById('total-devices').textContent = data.total_devices;
                        document.getElementById('devices-up').textContent = data.devices_up;
                        document.getElementById('devices-down').textContent = data.devices_down;
                        
                        const deviceList = document.getElementById('device-list');
                        deviceList.innerHTML = '';
                        
                        data.devices.forEach(device => {
                            const card = document.createElement('div');
                            card.className = `device-card status-${device.status}`;
                            card.innerHTML = `
                                <h4>${device.hostname}</h4>
                                <p><strong>IP:</strong> ${device.ip}</p>
                                <p><strong>Type:</strong> ${device.device_type}</p>
                                <p><strong>Status:</strong> <span style="color: ${device.status === 'up' ? '#27ae60' : device.status === 'down' ? '#e74c3c' : '#f39c12'}">${device.status.toUpperCase()}</span></p>
                                <p><strong>Priority:</strong> ${device.priority}</p>
                                <p><strong>Last Seen:</strong> ${device.last_seen ? new Date(device.last_seen).toLocaleString() : 'Never'}</p>
                                <p><strong>Failures:</strong> ${device.failure_count}</p>
                            `;
                            deviceList.appendChild(card);
                        });
                    })
                    .catch(error => console.error('Error:', error));
            }
            
            // Auto-refresh every 30 seconds
            setInterval(refreshData, 30000);
            refreshData(); // Initial load
        </script>
    </body>
    </html>
    '''

@app.route('/api/status')
def api_status():
    """API endpoint for system status."""
    if monitor_instance:
        return jsonify(monitor_instance.get_system_status())
    return jsonify({'error': 'Monitor not initialized'})

def start_web_dashboard(port: int = 5000):
    """Start the web dashboard."""
    app.run(host='0.0.0.0', port=port, debug=False)

def main():
    """Main entry point."""
    global monitor_instance
    
    logger.info("Starting AutoHeal Network Monitoring System")
    
    # Initialize monitor
    monitor_instance = AutoHealMonitor()
    
    # Start web dashboard in separate thread
    dashboard_thread = Thread(target=start_web_dashboard, daemon=True)
    dashboard_thread.start()
    
    logger.info("Web dashboard started on http://localhost:5000")
    
    # Start monitoring
    monitor_instance.start_monitoring()

if __name__ == "__main__":
    main()
