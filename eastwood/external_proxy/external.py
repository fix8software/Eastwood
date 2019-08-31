from quarry.net.protocol import BufferUnderrun

from eastwood.factories.mc_factory import MCFactory
from eastwood.modules import Module
from eastwood.protocols.mc_protocol import MCProtocol

class ExternalProxyExternalModule(Module):
	"""
	Internal module that keeps the external proxy's protocol mode updated
	Also manages connection limit
	"""
	def connectionMade(self):
		# Make sure we are not over the connection limit
		self.protocol.factory.num_connections += 1
		if self.protocol.factory.num_connections > self.protocol.factory.max_connections:
			self.protocol.transport.loseConnection() # Kick
			return

		# Tell the other mcprotocol
		try:
			self.protocol.other_factory.instance.send_packet("add_conn", self.protocol.buff_class.pack_uuid(self.protocol.uuid))
		except AttributeError:
			self.protocol.transport.loseConnection()

	def connectionLost(self, reason):
		# Subtract from conn limit
		self.protocol.factory.num_connections -= 1

		# Tell the internal mcprotocol
		try:
			self.protocol.other_factory.instance.send_packet("delete_conn", self.protocol.buff_class.pack_uuid(self.protocol.uuid))
		except AttributeError:
			pass

	def packet_recv_handshake(self, buff):
		"""
		Syphon protocol_mode from handshake packet
		Only sent serverbound (handled by the external proxy)
		https://wiki.vg/Protocol#Handshake
		"""
		buff.unpack_varint() # Protocol version
		buff.unpack_string() # Server ip
		buff.unpack("H") # Server host
		protocol_mode = buff.unpack_varint() # Protocol mode

		if protocol_mode == 1:
			self.protocol.protocol_mode = "status"
		elif protocol_mode == 2:
			self.protocol.protocol_mode = "login"

	def packet_send_login_success(self, buff):
		"""
		Set protocol_mode to play
		https://wiki.vg/Protocol#Handshake
		"""
		self.protocol.send_packet("login_success", buff.read()) # Send packet myself
		self.protocol.protocol_mode = "play" # Change mode after sending to prevent an error

		return ("login_success", None) # Prevent old packet from sending

class ExternalProxyExternalProtocol(MCProtocol):
	"""
	The ExternalProxyExternalProtocol intercepts all packets sent to this proxy
	The packets are then sent to ExternalProxyInternalProtocol to be buffered and then forwarded
	Sorry for the long name, it is to prevent people from confusing it with ExternalProxyInternalProtocol (which communicates with the internal proxy)
	"""
	def create(self):
		super().create()
		self.queue = [] # A queue exists at first to prevent packets from sending when the lan client/other mcprotocol hasn't been created yet

	def create_modules(self, modules):
		modules = [ExternalProxyExternalModule] + modules
		super().create_modules(modules)

	def packet_received(self, buff, name):
		# Intercept packet here
		if self.queue != None: # Queue exists, add them there instead
			# Handle packet first
			try:
				if not self.dispatch("_".join(("packet", "recv", name)), buff):
					self.packet_unhandled(buff, name)
			except BufferUnderrun:
				self.logger.info("Packet is too short: {}".format(name))
				return

			self.queue.append((self.uuid, name, buff))
			return

		# Append it to the buffer list
		super().packet_received(buff, name)

class ExternalProxyExternalFactory(MCFactory):
	"""
	Adds a connection limit to MCFactory
	"""
	protocol=ExternalProxyExternalProtocol

	def __init__(self, handle_direction, config):
		"""
		Args:
			handle_direction: direction packets being handled by this protocol are going (can be "clientbound" or "serverbound")
			config: config dict
		"""
		super().__init__(handle_direction, config)

		self.max_connections = config["external"]["player_limit"]
		self.num_connections = 0
