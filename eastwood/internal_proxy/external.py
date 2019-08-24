from twisted.internet import reactor
from twisted.internet.protocol import ClientFactory
from quarry.types.uuid import UUID

from eastwood.factories.mc_factory import MCFactory
from eastwood.protocols.mc_protocol import MCProtocol

class InternalProxyMCClientProtocol(MCProtocol):
	"""
	Emulated client connections to trick the server that everyone is connected on LAN
	"""
	def connectionMade(self):
		super().connectionMade()

		# Protocol is connected, allow the other MCProtocol to send packets
		self.other_factory.instance.send_packet("release_queue", self.buff_class.pack_uuid(self.uuid))

	def packet_login_success(self, buff):
		# Switch protocol mode to play
		self.protocol_mode = "play"

class InternalProxyMCClientFactory(MCFactory, ClientFactory):
	"""
	Manages client connections and also keeps track of their identity
	"""
	def __init__(self, protocol_version, mc_host, mc_port, ping_factory):
		"""
		Args:
			protocol_version: minecraft protocol specification to use
			mc_host: minecraft server's ip
			mc_port: minecraft server's port
			ping_factory: factory to ping the mc server
		"""
		super().__init__(protocol_version, "downstream")
		self.mc_host = mc_host
		self.mc_port = mc_port
		self.ping_factory = ping_factory
		self.ping_factory.callback = self.on_successful_ping

	def add_connection(self, uuid):
		"""
		Adds a connection to this factory
		Note: If there is a uuid conflict, undefined behavior will occur
		Args:
			uuid: idenifier of connection
		"""
		self.uuid_dict[uuid.to_hex()] = None # Reserve the spot (connection will be created by a ping call
		self.ping_factory.connect()

	def do_ping(self):
		# Only do the ping if there are null keys (reserved clients waiting to join)
		if None in self.uuid_dict.values():
			self.ping_factory.connect()

	def on_successful_ping(self):
		"""
		On a successful ping, create needed connections
		"""
		reactor.connectTCP(self.mc_host, self.mc_port, self)

	def buildProtocol(self, addr):
		# Build protocol with an unassigned uuid
		try:
			k = [*self.uuid_dict.keys()][[*self.uuid_dict.values()].index(None)]
			return InternalProxyMCClientProtocol(self, self.buff_class, self.handle_direction, self.other_factory, self.protocol_version, uuid=UUID(hex=k))
		except ValueError:
			pass

