"""
The proxy layer after the external proxy, runs on @Naphtha's homelab (thats real cool btw)
The internal proxy's job is to recieve packets from the external proxy and emulate connections on the LAN using that
It also sends server packets back to the external proxy to be distributed to the clients
"""

from twisted.internet import reactor
from twisted.internet.protocol import ClientFactory
from twisted.internet.task import LoopingCall
from quarry.types.uuid import UUID

from eastwood.protocols.ew_protocol import EWFactory, EWProtocol
from eastwood.protocols.mc_protocol import MCFactory, MCProtocol
from eastwood.server_pinger import ServerPingerFactory

class InternalProxyInternalProtocol(EWProtocol):
	"""
	Handles poems from the external proxy and sends them to the minecraft server, and vice versa
	"""
	def __init__(self, factory, buff_class, handle_direction, other_factory, buffer_wait, ip_forward):
		"""
		Protocol args:
			factory: factory that made this protocol (subclass of EWFactory)
			other_factory: the other factory that communicates with this protocol (in this case an instance of MCProtocol)
			buffer_wait: amount of time to wait before sending buffered packets (in ms)
			ip_forward: if true, forward the true ip
		"""
		super().__init__(factory, buff_class, handle_direction, other_factory, buffer_wait)
		self.ip_forward = ip_forward

	def packet_add_conn(self, buff):
		# Add a connection to InternalProxyMCClientFactory
		self.other_factory.add_connection(buff.unpack_uuid())

	def packet_delete_conn(self, buff):
		# Delete uuid connection
		uuid = buff.unpack_uuid()
		try:
			self.other_factory.get_client(uuid).transport.loseConnection()
		except KeyError:
			pass # Already gone
		except AttributeError:
			del self.other_factory.uuid_dict[uuid.to_hex()] # Delete the reference if it is none

	def packet_mc_handshake(self, uuid, buff):
		"""
		Syphon protocol_mode from handshake packet
		Only sent serverbound (handled by the external proxy)
		https://wiki.vg/Protocol#Handshake
		"""
		protocol_version = buff.unpack_varint() # Protocol version
		true_ip = buff.unpack_string() # Server ip
		true_port = buff.unpack("H") # Server host
		protocol_mode = buff.unpack_varint() # Protocol mode

		client = self.other_factory.get_client(uuid)
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
			new_data += buff.pack_string(self.other_factory.mc_host)
			new_data += buff.pack("H", self.other_factory.mc_port)

		new_data += buff.pack_varint(protocol_mode)

		client.send_packet("handshake", new_data) # Send packet myself
		client.protocol_mode = mode # Change mode after sending to prevent an error

		return (uuid, "handshake", None) # Prevent old packet from sending

class InternalProxyInternalFactory(EWFactory):
	"""
	Just passes the ip_forward option to InternalProxyInternalProtocol
	"""
	def __init__(self, protocol_version, handle_direction, buffer_wait, ip_forward):
		"""
		Args:
			protocol_version: minecraft protocol specification to use
			handle_direction: direction packets being handled by this protocol are going (can be "clientbound" or "serverbound")
			buffer_wait: amount of time to wait before sending buffered packets (in ms)
			ip_forward: if true, forward the true ip
		"""
		super().__init__(protocol_version, handle_direction, buffer_wait)
		self.ip_forward = ip_forward

	def buildProtocol(self, addr):
		return InternalProxyInternalProtocol(self, self.buff_class, self.handle_direction, self.other_factory, self.buffer_wait, self.ip_forward)

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


def create(protocol_version, host, port, mc_host, mc_port, buffer_wait, ip_forward):
	"""
	Create an instance of InternalProxyInternalProtocol which communicates with the external proxy
	Create an instance of InternalProxyMCClientFactory which controls the clients to the real server
	Args:
		protocol_version: protocol specification to use
		host: internal proxy's listening ip
		port: internal proxy's istening port
		mc_host: minecraft server's ip
		mc_port: minecraft server's port
		buffer_wait: amount of time to wait before sending buffered packets (in ms)
		ip_forward: if true, forward the true ip
	"""
	# Create an instance of InternalProxyInternalFactory which communicates with the external proxy
	internal_factory = InternalProxyInternalFactory(protocol_version, "upstream", buffer_wait, ip_forward)

	# Create an instance of InternalProxyMCClientFactory which controls the clients to the real server
	client_man = InternalProxyMCClientFactory(protocol_version, mc_host, mc_port, ServerPingerFactory(mc_host, mc_port))

	# Assign other_factory
	internal_factory.other_factory = client_man
	client_man.other_factory = internal_factory

	reactor.listenTCP(port, internal_factory, interface=host)
