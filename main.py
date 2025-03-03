from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,  ValidationError
from typing import List, Optional
import uvicorn
from fastapi.responses import HTMLResponse
import asyncio
import re
from jarvis import  Pool

import logging

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

def fetch_nodes_from_api(pools: List[str] = None):
    
    if not pools:
        pools = ['ahv-host-shared', 'ahv-host-shared-gpu', 'ahv-ipv6', 'ahv-maximum', 'apc-pool', 'ahv-g8-pool', 'ahv-g9-pool', '8Tb-pool']
        #pools = ['ahv-ipv6']
    
    res = []
    for pool in pools:
        p = Pool.from_name(pool)
       # print(p.name)
        for node in p.nodes:
            node_data = {
                "gpu_model": node.gpu_model,
                "cpu_cores": safe_int(node.num_cores), 
                "cpu_model": node.cpu,
                "cpu_generation": node.cpu_model,
                "cpu_sockets": safe_int(node.num_cpu_sockets), 
                "hostname": node.name,
                "host_ip": node.host_ip,
                "memory": node.memory,
                "pool": p.name
            }
            res.append(node_data)
    
    return res
    
@app.on_event("startup")
async def startup_event():
    global nodes
    nodes.clear()
    nodes_new = fetch_nodes_from_api()  # Initial fetch of all nodes
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
                cpu_model=item.get("cpu_model", "Unknown CPU")
            )
            nodes.append(node)
        except ValidationError as e:
            print(f"Skipping invalid node: {e}")
    
    asyncio.create_task(periodic_update())

async def periodic_update():
    while True:
        await asyncio.sleep(3000)
        new_nodes = fetch_nodes_from_api()
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
                    cpu_model=item.get("cpu_model", "Unknown CPU")
                )
                nodes.append(node)
            except ValidationError as e:
                print(f"Skipping invalid node: {e}")

@app.get("/api/nodes", response_model=List[Node])
async def get_nodes(
    gpu_model: str = None,
    min_cpu_cores: int = None,
    cpu_model: str = None,
    cpu_generation: str = None,
    cpu_sockets: int = None,
    hostname: str = None,
    host_ip: str = None,
    min_memory: int = None,
    pools: str = None  # Comma-separated pool names
):
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


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)