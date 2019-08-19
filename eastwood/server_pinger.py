"""
Protocol and factory that pings a minecraft server to see if it is open or not
"""
from twisted.internet import reactor
from quarry.net.client import PingClientFactory, PingClientProtocol

class ServerPingerProtocol(PingClientProtocol):
	"""
	Just tells the factory to run callbacks on success
	"""
	def status_response(self, data):
		self.factory.callback() # run the callback
		self.close()

class ServerPingerFactory(PingClientFactory):
	"""
	Factory that keeps track of server status
	"""
	protocol=ServerPingerProtocol

	def __init__(self, mc_host, mc_port):
		"""
		Args:
			mc_host: minecraft server's ip
			mc_port: minecraft server's port
		"""
		super().__init__()
		self.mc_host = mc_host
		self.mc_port = mc_port
		self.callback = None # Callback on successful ping

	def connect(self):
		reactor.connectTCP(self.mc_host, self.mc_port, self, self.connection_timeout)
