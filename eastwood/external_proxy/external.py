from quarry.net.protocol import BufferUnderrun

from eastwood.factories.mc_factory import MCFactory
from eastwood.protocols.mc_protocol import MCProtocol

class ExternalProxyBungeeCordFrontEndProtocol(MCProtocol):
	"""
	The ExternalProxyBungeeCordFrontEndProtocol intercepts all packets sent to this proxy
	The packets are then sent to ExternalProxyInternalProtocol to be buffered and then forwarded
	Sorry for the long name, it is to prevent people from confusing it with ExternalProxyInternalProtocol (which communicates with the internal proxy)
	"""
	def __init__(self, factory, buff_class, handle_direction, other_factory, protocol_version, uuid=None):
		"""
		Protocol args:
			factory: factory that made this protocol (subclass of BaseFactory)
			buff_class: buffer class that this protocol will use
			handle_direction: direction packets being handled by this protocol are going (can be "downstream" or "upstream")
			other_factory: the other factory that communicates with this protocol (in this case an instance of EWProtocol)
			protocol_version: protocol specification to use
			uuid: uuid of client, don't set to autogen
		"""
		super().__init__(factory, buff_class, handle_direction, other_factory, protocol_version, uuid)
		self.queue = [] # A queue exists at first to prevent packets from sending when the lan client/other mcprotocol hasn't been created yet

	def connectionMade(self):
		# Make sure we are not over the connection limit
		self.factory.num_connections += 1
		if self.factory.num_connections > self.factory.max_connections:
			self.transport.loseConnection() # Kick
			return

		super().connectionMade()

		# Tell the other mcprotocol
		try:
			self.other_factory.instance.send_packet("add_conn", self.buff_class.pack_uuid(self.uuid))
		except AttributeError:
			self.transport.loseConnection()

	def connectionLost(self, reason):
		super().connectionLost(reason)

		# Subtract from conn limit
		self.factory.num_connections += 1

		# Tell the internal mcprotocol
		try:
			self.other_factory.instance.send_packet("delete_conn", self.buff_class.pack_uuid(self.uuid))
		except AttributeError:
			pass

	def packet_received(self, buff, name):
		# Intercept packet here
		if self.queue != None: # Queue exists, add them there instead
			# Handle packet first
			try:
				if not self.dispatch((name,), buff):
					self.packet_unhandled(buff, name)
			except BufferUnderrun:
				self.logger.info("Packet is too short: {}".format(name))
				return

			self.queue.append((self.uuid, name, buff))
			return

		# Append it to the buffer list
		super().packet_received(buff, name)

	def packet_handshake(self, buff):
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
			self.protocol_mode = "status"
		elif protocol_mode == 2:
			self.protocol_mode = "login"

class ExternalProxyBungeeCordFrontEndFactory(MCFactory):
	"""
	Adds a connection limit to MCFactory
	"""
	protocol=ExternalProxyBungeeCordFrontEndProtocol

	def __init__(self, protocol_version, handle_direction, max_connections):
		"""
		Args:
			protocol_version: minecraft protocol specification to use
			handle_direction: direction packets being handled by this protocol are going (can be "clientbound" or "serverbound")
			max_connections: max amount of clients to accept before kicking
		"""
		super().__init__(protocol_version, handle_direction)

		self.max_connections = max_connections
		self.num_connections = 0
