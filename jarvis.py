#! /usr/bin/python3
# coding=utf8
#
# Copyright (c) 2022 Nutanix Inc. All rights reserved.
#
# Author: Felipe Franciosi <felipe@nutanix.com>

"""
Jarvis python bindings.

Usage:
>>> from jarvis import Pool, Node, Cluster
>>> p = Pool.from_name('ahv-host-shared')
>>> p.oid
'623873454dd192c93d20a831'
>>> p.name
'ahv-host-shared'
>>> # Alternatively
>>> p = Pool.from_oid('623873454dd192c93d20a831')
>>> p.nodes
[...]
>>> n = Node.from_oid(p.nodes[0])
>>> # And so on...
"""

import json

from abc import ABC
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from logging import debug as ldbg
from queue import Queue

import requests
from requests.packages import urllib3

class Jarvis(ABC):
  """
  Abstract Jarvis class to derive entities from.
  """
  url = 'https://jarvis.eng.nutanix.com/api/v1/'
  hdr = {'Accept': 'application/json'}
  timeout = 600
  endpoint = None

  def __init__(self, obj):
    assert isinstance(obj, dict)
    self._obj = obj

  @classmethod
  def from_name(cls, name):
    """
    Creates a new object from name.
    """
    assert isinstance(name, str)

    rsp = cls._get(params={'search': f'^{name}$'})
    num_objs = rsp['total']
    if num_objs != 1:
      raise ValueError(f'Found {num_objs} {cls.__name__}(s) instead of 1 '
                       f'when searching for name "{name}"')
    objs = rsp['data']
    ldbg(f'objs = {objs}')
    assert len(objs) == 1
    return cls(objs[0])

  @classmethod
  def from_oid(cls, oid):
    """
    Creates a new object from oid.
    """
    assert isinstance(oid, str)

    rsp = cls._get(oid=oid)
    return cls(rsp['data'])

  @staticmethod
  def _get_name(obj):
    """
    Returns the name of the object for this class.
    """
    return obj['name']

  @classmethod
  def _get(cls, oid=None, params=None):
    """
    If @oid, fetches one object from Jarvis.
    Otherwise fetches a list of objects with an optional query @params.
    """
    assert oid is None or isinstance(oid, str)
    assert params is None or isinstance(params, dict)
    assert (oid is None) != (params is None)

    urllib3.disable_warnings()

    url = f'{cls.url}/{cls.endpoint}'
    if oid:
      url += f'/{oid}'

    # Disable pagination if it hasn't been explicitly enabled.
    params = params or {}
    if 'paginate' not in params:
      params['paginate'] = 'false'
    # nb. str(False) is 'False', but Jarvis only understands 'false'.

    ldbg(f'GET {url}')
    # print(url)
    rsp = requests.get(url, headers=cls.hdr, params=params, timeout=cls.timeout,
                       verify=False)
    rsp_json = rsp.json()
    ldbg(f'GOT {rsp_json}')
    return rsp_json

  @classmethod
  def _raw_query(cls, raw_query):
    """
    Performs a raw query on Jarvis.
    """
    return cls._get(params={'raw_query':json.dumps(raw_query)})

  @classmethod
  def _get_distinct(cls, path):
    """
    Fetches a list of distinct objects in @path.
    """
    rsp = cls._get(params={'distinct':path}).get('data')
    if rsp is not None:
      return rsp[0][path]
    return []

  @property
  def oid(self):
    """
    Returns the OID of the object.
    """
    return self._obj['_id']['$oid']

  @property
  def name(self):
    """
    Returns the name of the object.
    """
    return self._obj['name']

  @property
  def raw(self):
    """
    Returns the raw object.
    """
    return self._obj

class JarvisWithNodes(Jarvis):
  """
  A Jarvis object which has the "nodes" property.
  """
  def __init__(self, obj):
    self._nodes = None
    super().__init__(obj)

  @property
  def nodes(self):
    """
    Returns a list of Nodes from this object.
    """
    if self._nodes is None:
      def get_node_thr(oid, queue):
        node = Node.from_oid(oid)
        queue.put(node)

      nodes_q = Queue()
      with ThreadPoolExecutor(max_workers=50) as executor:
        for node in self._obj['nodes']:
          executor.submit(get_node_thr, node['$oid'], nodes_q)

      self._nodes = list(nodes_q.queue)

    return self._nodes

class Pool(JarvisWithNodes):
  """
  A Jarvis pool.
  """
  url = 'https://jarvis.eng.nutanix.com/api/v2/'
  endpoint = 'pools'

  @property
  def clusters(self):
    """
    Returns a list of clusters' OIDs from this pool.
    """
    return [cluster['$oid'] for cluster in self._obj['clusters']]

  @property
  def users(self):
    """
    Returns a list of users' OIDs from this pool.
    """
    return [user['$oid'] for user in self._obj['users']]
  

class Cluster(JarvisWithNodes):
  """
  A Jarvis cluster.
  """
  endpoint = 'clusters'

  @property
  def created_by(self):
    """
    Returns the name of the user which created the cluster.
    """
    return self._obj['client']['owner']

  @property
  def created_at(self):
    """
    Returns a datetime representing when the cluster was created.
    """
    return str(datetime.fromtimestamp(self._obj['created_at']['$date']/1000,
                                      tz=timezone.utc))

  @property
  def owner_name(self):
    """
    Returns the name of the current owner.
    """
    return self._obj['owner']['display_name']

  @property
  def nodes(self):
    """
    Returns the nodes in the cluster
    """
    return self._obj['nodes']

class Block(JarvisWithNodes):
  """
  A Jarvis block.
  """
  endpoint = 'blocks'

  @staticmethod
  def from_node_oid(node_oid):
    """
    Constructs a Block object from a Node's OID.
    """
    assert isinstance(node_oid, str)
    raw = Block._raw_query({'nodes':node_oid})
    num_blocks = raw['total']
    if num_blocks != 1:
      raise ValueError(f'Found {num_blocks} Blocks instead of 1 when '
                       f'searching for node_oid "{node_oid}"')
    return Block(raw['data'][0])

  @staticmethod
  def from_node_name(node_name):
    """
    Constructs a Block object from a Node's Name.
    """
    assert isinstance(node_name, str)
    node = Node.from_name(node_name)
    return Block.from_node_oid(node.oid)

  @property
  def owner(self):
    """
    Returns the display_name of the Block owner.
    """
    return self._obj['ownership']['owner']['display_name']

  @property
  def rack(self):
    """
    Returns the physical location of the block in the data centre.
    """
    return self._obj['rack']

class Node(Jarvis):
  """
  A Jarvis node.
  """
  endpoint = 'nodes'

  @staticmethod
  def _from_raw_query(raw_query):
    """
    Constructs a Node object from a raw query.
    """
    rsp = Node._raw_query(raw_query)
    num_nodes=rsp['total']
    if num_nodes != 1:
      raise ValueError(f'Found {num_nodes} Nodes instead of 1 when '
                       f'using query: "{raw_query}"')
    return Node(rsp['data'][0])

  @staticmethod
  def from_host_ip(host_ip):
    """
    Constructs a Node object from its @hypervisor.ip.
    """
    return Node._from_raw_query({'hypervisor.ip':host_ip})

  @staticmethod
  def from_svm_ip(svm_ip):
    """
    Constructs a Node object from its @svm_ip.
    """
    return Node._from_raw_query({'svm_ip':svm_ip})

  @staticmethod
  def nodes_with_gpu(gpu_model):
    """
    Returns a list of Nodes fitted with @gpu_model.
    """
    assert isinstance(gpu_model, str)
    raw = Node._raw_query({'hardware.gpu_model':gpu_model})
    return [Node(n) for n in raw['data']]

  @staticmethod
  def _get_name(obj):
    return obj['network']['hostname']

  @property
  def name(self):
    """
    Returns the name of the object.
    """
    return self._obj['network']['hostname']

  @property
  def host_ip(self):
    """
    Returns the IP of the Node.
    """
    return self._obj['hypervisor']['ip']

  @property
  def cluster(self):
    """
    Returns the OID of the cluster this node belongs to or None.
    """
    cluster = self._obj.get('cluster')
    if cluster:
      return cluster['_id']['$oid']
    return None

  @property
  def enabled(self):
    """
    Returns whether the node is enabled or not.
    """
    return self._obj['is_enabled']

  @property
  def svm_net(self):
    """
    Returns network information for the SVM.
    """
    return {
      'ip': self._obj.get('svm_ip'),
      'netmask': self._obj['network'].get('svm_subnet_mask'),
      'gateway': self._obj['network'].get('default_gw')
    }

  @property
  def bmc(self):
    """
    Returns the ip, user, and pass for this node's BMC.
    """
    # This should work for all platforms.
    bmc = self._obj['power_mgmt']['ipmi']
    return {
      'ip': bmc['ip'],
      'user': bmc['user'],
      'passwd': bmc['passwd']
    }

  @property
  def gpu_model(self):
    """
    Returns the gpu model in this Node or None if no GPU configured.
    """
    return self._obj['hardware'].get('gpu_model')

  @property
  def memory(self):
    """
    Returns the amount of memory for this node.
    """
    return self._obj['hardware'].get('mem')

  @property
  def cpu_model(self):
    """
    Returns the model for this node.
    """
    return self._obj['hardware'].get('model')

  @property
  def num_cores(self):
    """
    Returns the number of cores for this node.
    """
    return self._obj['hardware'].get('cpu_cores') 

  @property
  def pool(self):
    """
    Returns the name of the pool this Node is in or None if not in any.
    """
    return self._obj.get('node_pool')

  @property
  def cpu(self):
      return self._obj['hardware'].get('cpu') 
  
  @property
  def num_cpu_sockets(self):
      return self._obj['hardware'].get('num_cpu_sockets') 

  @property
  def serial(self):
    """
    Returns the Node's serial number.
    """
    return self._obj['hardware']['serial']

# vim: set ts=2 sw=2 et:
