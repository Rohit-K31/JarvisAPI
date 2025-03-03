from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from fastapi.responses import HTMLResponse
import asyncio
from jarvis import  Pool

app = FastAPI()

class Node(BaseModel):
    hostname: Optional[str]
    memory: Optional[str]
    cpu_cores: Optional[str]
    cpu_generation: Optional[str]
    cpu_sockets: Optional[str]
    host_ip: Optional[str]
    gpu_model: Optional[str]
    pool: Optional[str]
    cpu_model: Optional[str]
    

nodes = []
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
                "cpu_cores": str(node.num_cores), 
                "cpu_model": node.cpu,
                "cpu_generation": node.cpu_model,
                "cpu_sockets": str(node.num_cpu_sockets), 
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
    nodes = fetch_nodes_from_api()  # Initial fetch of all nodes
    
    asyncio.create_task(periodic_update())

async def periodic_update():
    while True:
        await asyncio.sleep(3000)
        new_nodes = fetch_nodes_from_api()
        nodes.clear()
        nodes = [
            Node(
                gpu_model=node.get("gpu_model"),
                cpu_cores=node.get("cpu_cores"),
                cpu_model=node["cpu_model"],
                cpu_generation=node["cpu_generation"],
                cpu_sockets=node["cpu_sockets"],
                hostname=node["hostname"],
                host_ip=node["host_ip"],
                memory=node["memory"],
                pool=node["pool"]
            )
            for node in new_nodes
        ]

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
    filtered = nodes
    
    # Text filters
    if gpu_model:
        filtered = [n for n in filtered if gpu_model.lower() in n.gpu_model.lower()]
    if cpu_model:
        filtered = [n for n in filtered if cpu_model.lower() in n.cpu_model.lower()]
    if cpu_generation:
        filtered = [n for n in filtered if cpu_generation.lower() in n.cpu_generation.lower()]
    if hostname:
        filtered = [n for n in filtered if hostname.lower() in n.hostname.lower()]
    if host_ip:
        filtered = [n for n in filtered if host_ip in n.host_ip]

    if min_cpu_cores:
        filtered = [n for n in filtered if n.cpu_cores  and int(n.cpu_cores) >= min_cpu_cores]
    if cpu_sockets:
        filtered = [n for n in filtered if n.cpu_sockets  and int(n.cpu_sockets) == cpu_sockets]
    if min_memory:
        filtered = [n for n in filtered if n.memory and int(n.memory.replace("GB", "")) >= min_memory]

   
    if pools:
        pool_list = [p.strip().lower() for p in pools.split(",")]
        filtered = [n for n in filtered if n.pool.lower() in pool_list]
    
    return filtered


app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)