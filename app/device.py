# device.py
from dataclasses import dataclass

@dataclass
class Device:
    ip: str
    community: str = 'public'
    name: str = ''
    
    def __post_init__(self):
        if not self.name:
            self.name = self.ip
