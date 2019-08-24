from twisted.internet import reactor
from twisted.internet.protocol import ClientFactory
from quarry.types.uuid import UUID

from eastwood.factories.mc_factory import MCFactory
from eastwood.protocols.mc_protocol import MCProtocol

class InternalProxyExternalProtocol(MCProtocol):
	"""
	Emulated client connections to trick the server that everyone is connected on LAN
	"""
	def __init__(self, factory, buff_class, handle_direction, other_factory, buffer_wait, ip_forward, uuid=None):
		"""
		Protocol args:
			factory: factory that made this protocol (subclass of BaseFactory)
			buff_class: buffer class that this protocol will use
			handle_direction: direction packets being handled by this protocol are going (can be "downstream" or "upstream")
			other_factory: the other factory that communicates with this protocol (in this case an instance of EWProtocol)
			protocol_version: protocol specification to use
			ip_forward: if true, forward the true ip
			uuid: uuid of client, don't set to autogen
		"""
		super().__init__(factory, buff_class, handle_direction, other_factory, buffer_wait, uuid=uuid)
		self.ip_forward = ip_forward

	def connectionMade(self):
		super().connectionMade()

		# Protocol is connected, allow the other MCProtocol to send packets
		self.other_factory.instance.send_packet("release_queue", self.buff_class.pack_uuid(self.uuid))

	def packet_recv_login_success(self, buff):
		# Switch protocol mode to play
		self.protocol_mode = "play"

	def packet_send_handshake(self, buff):
		"""
		Syphon protocol_mode from handshake packet
		Only sent serverbound (handled by the external proxy)
		https://wiki.vg/Protocol#Handshake
		"""
		protocol_version = buff.unpack_varint() # Protocol version
		true_ip = buff.unpack_string() # Server ip
		true_port = buff.unpack("H") # Server host
		protocol_mode = buff.unpack_varint() # Protocol mode

		if protocol_mode == 1: # Set the protocol mode accordingly
			mode = "status"
		elif protocol_mode == 2:
			mode = "login"

		# Change port number
		new_data = buff.pack_varint(protocol_version)

		# Only fake the ip if we are using bungeecord
		if self.ip_forward:
			new_data += buff.pack_string(true_ip)
			new_data += buff.pack("H", true_port)
		else:
			new_data += buff.pack_string(self.factory.mc_host)
			new_data += buff.pack("H", self.factory.mc_port)

		new_data += buff.pack_varint(protocol_mode)

		self.send_packet("handshake", new_data) # Send packet myself
		self.protocol_mode = mode # Change mode after sending to prevent an error

		return ("handshake", None) # Prevent old packet from sending


class InternalProxyExternalFactory(MCFactory, ClientFactory):
	"""
	Manages client connections and also keeps track of their identity
	"""
	def __init__(self, protocol_version, mc_host, mc_port, ip_forward, ping_factory):
		"""
		Args:
			protocol_version: minecraft protocol specification to use
			mc_host: minecraft server's ip
			mc_port: minecraft server's port
			ip_forward: if true, forward the true ip
			ping_factory: factory to ping the mc server
		"""
		super().__init__(protocol_version, "downstream")
		self.mc_host = mc_host
		self.mc_port = mc_port
		self.ip_forward = ip_forward
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
			return InternalProxyExternalProtocol(self, self.buff_class, self.handle_direction, self.other_factory, self.protocol_version, self.ip_forward, uuid=UUID(hex=k))
		except ValueError:
			pass
