from twisted.internet import reactor
from twisted.internet.protocol import ClientFactory
from quarry.types.uuid import UUID

from eastwood.factories.mc_factory import MCFactory
from eastwood.misc import parse_ip_port
from eastwood.modules import Module
from eastwood.protocols.mc_protocol import MCProtocol
from eastwood.server_pinger import ServerPingerFactory

class InternalProxyExternalModule(Module):
	"""
	Internal module for the internal proxy's external portion
	"""
	def __init__(self, protocol):
		super().__init__(protocol)

		self.dimension = 0 # Player dimension, used for tracking chunks

	def connectionMade(self):
		# Protocol is connected, allow the other MCProtocol to send packets
		self.protocol.other_factory.instance.send_packet("release_queue", self.protocol.buff_class.pack_uuid(self.protocol.uuid))

	def packet_recv_login_success(self, buff):
		# Switch protocol mode to play
		self.protocol.protocol_mode = "play"

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
		if self.protocol.ip_forward:
			new_data += buff.pack_string(true_ip)
			new_data += buff.pack("H", true_port)
		else:
			new_data += buff.pack_string(self.protocol.factory.mc_host)
			new_data += buff.pack("H", self.protocol.factory.mc_port)

		new_data += buff.pack_varint(protocol_mode)

		self.protocol.send_packet("handshake", new_data) # Send packet myself
		self.protocol.protocol_mode = mode # Change mode after sending to prevent an error

		return ("handshake", None) # Prevent old packet from sending

	def packet_recv_join_game(self, buff):
		"""
		Called when the client joins the game, we need to capture the dimension
		"""
		self.dimension = buff.unpack("ibi")[2] # Ignore entity id and gamemode

	def packet_recv_respawn(self, buff):
		"""
		Same here, need to capture the dimension
		"""
		self.dimension = buff.unpack("i") # Dimension is the first packed field

	def packet_recv_chunk_data(self, buff):
		"""
		If chunk is cached on the other side, strip chunk packet of all data instead of the key
		"""
		chunk_x, chunk_z, full_chunk = buff.unpack("ii?") # Use the chunk x and z values in bytes as the key
		chunk_key = self.protocol.buff_class.pack("ii", chunk_x, chunk_z)

		if not full_chunk:
			return # Ignore full chunks

		if chunk_key in self.protocol.factory.cache_lists[self.dimension]:
			# Send stripped chunk packet if cached
			return ("chunk_data", self.protocol.buff_class(b"".join((chunk_key, self.protocol.buff_class.pack("?", True)))))

class InternalProxyExternalProtocol(MCProtocol):
	"""
	Emulated client connections to trick the server that everyone is connected on LAN
	"""
	def create(self):
		super().create()
		self.ip_forward = self.config["global"]["ip_forwarding"]

	def create_modules(self, modules):
		super().create_modules((InternalProxyExternalModule,) + modules)

class InternalProxyExternalFactory(MCFactory, ClientFactory):
	"""
	Manages client connections and also keeps track of their identity
	"""
	def __init__(self, config):
		"""
		Args:
			config: config dict
		"""
		super().__init__("downstream", config)
		self.mc_host, self.mc_port = parse_ip_port(config["internal"]["minecraft"])
		self.ping_factory = ServerPingerFactory(self.mc_host, self.mc_port)
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
			pc = InternalProxyExternalProtocol(self, self.buff_class, self.handle_direction, self.other_factory, self.config)
			pc.uuid = UUID(hex=k)
			return pc
		except ValueError:
			pass
