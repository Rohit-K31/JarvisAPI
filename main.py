from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,  ValidationError
from typing import List, Optional
import uvicorn
import asyncssh
import asyncio
from ping3 import ping
from fastapi.responses import HTMLResponse
import asyncio
from decouple import config
import re
from jarvis import  Pool

import logging

UPDATE_INTERVAL = config("UPDATE_INTERVAL", default=300, cast=int)
SSH_USERNAME = config("SSH_USERNAME", default="root")
SSH_PASSWORD = config("SSH_PASSWORD", default="RDMCluster.123")  # Password from environment


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

class Node(BaseModel):
    hostname: Optional[str]
    memory: Optional[str]
    cpu_cores: Optional[int]
    cpu_generation: Optional[str]
    cpu_sockets: Optional[int]
    host_ip: Optional[str]
    gpu_model: Optional[str]
    pool: Optional[str]
    cpu_model: Optional[str]
    nics_count: Optional[int] = None
    nic_speed: Optional[str] = None
    
    @classmethod
    def parse_memory(cls, memory_str: str) -> int:
        """Convert memory strings like '256GB', '256 Gb', '1TB' to integer GB"""
        try:
            # Regex to extract numeric value and unit
            match = re.match(r'^\s*(\d+)\s*(TB|GB|T|G)?', memory_str, re.IGNORECASE)
            if not match:
                return 0
            
            value, unit = match.groups()
            unit = unit.upper() if unit else 'GB'  # Default to GB
            
            if unit.startswith('T'):
                return int(value) * 1024
            return int(value)
        except (ValueError, AttributeError):
            return 0


nodes = []

def safe_int(value, default=0):
    try:
        return int(value) if value else default
    except (ValueError, TypeError):
        return default

async def fetch_nodes_from_api(pools: List[str] = None):
    
    if not pools:
        # pools = ['ahv-host-shared', 'ahv-host-shared-gpu', 'ahv-ipv6', 'ahv-maximum', 'apc-pool', 'ahv-g8-pool', 'ahv-g9-pool', '8Tb-pool', 'AHV-AMD']
        # pools = ['apc-pool']
        pools = ['ahv-host-shared-gpu']
    
    res = []
    for pool in pools:
        p = Pool.from_name(pool)
       # print(p.name)
        for node in p.nodes:
            hardware_data =  await  get_hardware_info(node.host_ip)
            # print(node.name)
            logger.info(f"NIC Data: {hardware_data}")
            nics_count  = hardware_data.get("nics_count", 0)
            nic_speed = hardware_data.get("nic_speed",0)
            gpu_model = hardware_data.get("gpu_model", "")
            if gpu_model=="":
                gpu_model = node.gpu_model
            # print("nc = %s, ns = %s" % (nics_count, nic_speed))
            # continue
            node_data = {
                "gpu_model": gpu_model,
                "cpu_cores": safe_int(node.num_cores), 
                "cpu_model": classify_cpu(node.cpu),
                "cpu_generation": node.cpu_model,
                "cpu_sockets": safe_int(node.num_cpu_sockets), 
                "hostname": node.name,
                "host_ip": node.host_ip,
                "memory": node.memory,
                "pool": p.name,
                "nics_count": nics_count, 
                "nic_speed": nic_speed
            }
            res.append(node_data)
            
    return res
    
@app.on_event("startup")
async def startup_event():
    global nodes
    nodes.clear()
    nodes_new = await fetch_nodes_from_api()  # Initial fetch of all nodes
    for item in nodes_new:
        try:
            # Create Node instance with validation
            node = Node(
                hostname=item.get("hostname", "unknown-host"),
                memory=item.get("memory", "0GB"),
                cpu_cores=item.get("cpu_cores", 0),
                cpu_generation=item.get("cpu_generation", "N/A"),
                cpu_sockets=item.get("cpu_sockets", 0),
                host_ip=item.get("host_ip", "0.0.0.0"),
                gpu_model=item.get("gpu_model"),
                pool=item.get("pool", "default"),
                cpu_model=item.get("cpu_model", "Unknown CPU"),
                nics_count = item.get("nics_count", 0),
                nic_speed=  item.get("nic_speed", 0)
                
            )
            nodes.append(node)
        except ValidationError as e:
            print(f"Skipping invalid node: {e}")
    
    asyncio.create_task(periodic_update())

async def periodic_update():
    while True:
        await asyncio.sleep(3000)
        new_nodes = await fetch_nodes_from_api()
        nodes.clear()
        for item in new_nodes:
            try:
                # Create Node instance with validation
                node = Node(
                    hostname=item.get("hostname", "unknown-host"),
                    memory=item.get("memory", "0GB"),
                    cpu_cores=item.get("cpu_cores", 0),
                    cpu_generation=item.get("cpu_generation", "N/A"),
                    cpu_sockets=item.get("cpu_sockets", 0),
                    host_ip=item.get("host_ip", "0.0.0.0"),
                    gpu_model=item.get("gpu_model"),
                    pool=item.get("pool", "default"),
                    cpu_model=item.get("cpu_model", "Unknown CPU"),
                    nics_count = item.get("nics_count", 0),
                    nic_speed=  item.get("nic_speed", 0)
                )
                nodes.append(node)
            except ValidationError as e:
                print(f"Skipping invalid node: {e}")

@app.get("/api/nodes", response_model=List[Node])
async def get_nodes(gpu_model: str = None, min_cpu_cores: int = None,
        cpu_model: str = None, cpu_generation: str = None, cpu_sockets: int = None,
        hostname: str = None, host_ip: str = None, min_memory: int = None,
        pools: str = None):
        
        logger.info(f"Received query: {locals()}")  # Log incoming parameters
        filtered = nodes
    
        # Text filters
        if hostname:
            filtered = [n for n in filtered if hostname.lower() in n.hostname.lower()]
        if min_memory:
            filtered = [n for n in filtered if Node.parse_memory(n.memory) >= min_memory]
        if min_cpu_cores:
            filtered = [n for n in filtered if n.cpu_cores >= min_cpu_cores]
        if cpu_generation:
            filtered = [n for n in filtered if cpu_generation.lower() in n.cpu_generation.lower()]
        if cpu_sockets:
            filtered = [n for n in filtered if n.cpu_sockets == cpu_sockets]
        if host_ip:
            filtered = [n for n in filtered if host_ip in n.host_ip]
        if gpu_model:
            filtered = [n for n in filtered if n.gpu_model and gpu_model.lower() in n.gpu_model.lower()]
        if pools:
            pool_list = [p.strip().lower() for p in pools.split(",")]
            filtered = [n for n in filtered if n.pool.lower() in pool_list]
        if cpu_model:
            filtered = [n for n in filtered if cpu_model.lower() in n.cpu_model.lower()]
        
        return filtered
    

async def get_hardware_info(ip: str) -> dict:
    if not ping(ip):
        logger.warning(f"Host {ip} unreachable")
        return {}

    try:
        async with asyncssh.connect(
            ip,
            username=SSH_USERNAME,
            password=SSH_PASSWORD,
            known_hosts=None
        ) as conn:
             # Get NIC count
            result = await conn.run("lspci | grep -ci 'ethernet'")
            nics_count = int(result.stdout.strip()) if result.exit_status == 0 else None

            # Get NIC speeds
            result = await conn.run(
                "for iface in $(ls /sys/class/net | grep -v lo); do "
                "echo -n \"$iface: \" && ethtool $iface | grep Speed; "
                "done"
            )
            nic_speed = None
            if result.exit_status == 0:
                speeds = [line.split(": ")[-1].strip() for line in result.stdout.splitlines() if "Speed" in line]
                nic_speed = ", ".join(speeds) if speeds else None

            # Get GPU model (NVIDIA/AMD)
            result = await conn.run("nvidia-smi --query-gpu=name --format=csv,noheader")
            if result.exit_status == 0:
                gpu_model = result.stdout.strip()
            else:
                # Fallback for AMD or other GPUs
                result = await conn.run("lspci | grep -i 'vga\|amd\|nvidia'")
                gpu_model = result.stdout.strip() if result.exit_status == 0 else None

            return {
                "nics_count": nics_count,
                "nic_speed": nic_speed,
                "gpu_model": gpu_model
            }

    except asyncssh.misc.PermissionDenied:
        logger.error(f"Authentication failed for {ip}")
        #return {}
        return {"nics_count": 0, "nic_speed": 0, "gpu_model":""}
    except Exception as e:
        logger.error(f"SSH failed for {ip}: {e}")
        # return {}
        return {"nics_count": 0, "nic_speed": 0, "gpu_model":""}
    
    
# async def enrich_node_data(base_node: dict) -> Node:
#     nic_data = await get_nic_info(base_node["host_ip"])
#     return Node(**base_node, **nic_data)


def classify_cpu(cpu_name):
    cpu_name_ = cpu_name
    cpu_name = cpu_name.strip()
    if not cpu_name:
        return cpu_name

    if cpu_name.startswith('Intel'):
        try:
            after_xeon = cpu_name.split('Xeon(R) ')[1]
            parts = after_xeon.split()
            brand = parts[0] if parts else ''

            # Handle Scalable Processors (Skylake and newer)
            if brand in ['Gold', 'Silver', 'Platinum']:
                model_part = parts[1] if len(parts) > 1 else ''
                numeric_model = ''.join(c for c in model_part if c.isdigit())
                if len(numeric_model) < 2:
                    return f"Unknown: ({cpu_name_})"
                key = numeric_model[:2]
                intel_generations = {
                    '53': 'CooperLake', #(3rd Gen)',  # Added for 53xx models
                    '54': 'CooperLake', # (3rd Gen)', 
                    '61': 'Skylake', # (1st Gen Scalable)',
                    '62': 'CascadeLake', # (2nd Gen)',
                    '63': 'CooperLake', # (3rd Gen)',
                    '64': 'IceLake', # (4th Gen)',
                    '83': 'IceLake', # (4th Gen)',
                    '43': 'IceLake', # (4th Gen)',
                    '65': 'Sapphire Rapids', # (5th Gen)',
                    '84': 'Sapphire Rapids', # (5th Gen)',
                    '85': 'Sapphire Rapids', # (5th Gen)',
                    '66': 'Emerald Rapids', # (6th Gen)',  # Newer generation
                    '86': 'Emerald Rapids', # (6th Gen)',  # Assume future model numbers
                }
                generation = intel_generations.get(key, f'{cpu_name_}')
                if generation.startswith('Intel'):
                    return generation
                return f"Intel {generation}"

            # Handle Older Xeon E5/E7 (Haswell, Broadwell, etc.)
            elif brand == 'CPU':
                model_part = parts[1] if len(parts) > 1 else ''
                version = None
                for part in parts:
                    if part.startswith('v') and part[1:].isdigit():
                        version = part
                        break
                if version:
                    version_map = {
                        'v2': 'Ivy Bridge-EP', # (2nd Gen Xeon)',
                        'v3': 'Haswell-EP', # (3rd Gen Xeon)',
                        'v4': 'Broadwell-EP', # (4th Gen Xeon)',
                    }
                    generation = version_map.get(version, f'{cpu_name_}')
                    return f"Intel Xeon {version} ({generation})"
                else:
                    return f"Intel Xeon (Pre-Scalable, Unknown Gen)"

            else:
                return f"{cpu_name_}"

        except (IndexError, ValueError):
            return f"{cpu_name_}"

    elif cpu_name.startswith('AMD'):
        try:
            parts = cpu_name.split()
            model = None
            for part in parts:
                if len(part) >= 4 and part[:4].isdigit():
                    model_part = part
                    model = part[:4]  # Extract first 4 digits (e.g., "7702P" → "7702")
                    break
            if not model:
                return f"{cpu_name_}"
            if model.startswith('7'):
                gen_digit = model[3]
                generation_map = {
                    '1': 'Naples (1st Gen)',
                    '2': 'Rome (2nd Gen)',
                    '3': 'Milan (3rd Gen)',
                }
                generation = generation_map.get(gen_digit, 'Unknown')
                return f"AMD EPYC {generation}"
            elif model.startswith('9'):
                gen_digit = model[3]
                generation_map = {
                    '4': 'Genoa (4th Gen)',
                    '5': 'Bergamo (5th Gen)',
                    '6': 'Genoa-X (6th Gen)',  # Future-proofing
                }
                generation = generation_map.get(gen_digit, 'Unknown')
                return f"AMD EPYC {generation}"
            else:
                return f"{cpu_name_}"
        except (IndexError, ValueError):
            return f"{cpu_name_}"

    else:
        return f"{cpu_name_}"


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)