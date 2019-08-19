"""
The proxy layer after bungeecord and before the internal proxy, runs on the vps
Acts as a proxy to intercept, encode, and send minecraft packets to the internal proxy
"""

from quarry.net.protocol import BufferUnderrun
from twisted.internet import reactor
from twisted.internet.protocol import ReconnectingClientFactory

from eastwood.protocols.ew_protocol import EWFactory, EWProtocol
from eastwood.protocols.mc_protocol import MCFactory, MCProtocol

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
		super().connectionMade()

		# Tell the other mcprotocol
		try:
			self.other_factory.instance.send_packet("add_conn", self.buff_class.pack_uuid(self.uuid))
		except AttributeError:
			self.transport.loseConnection()

	def connectionLost(self, reason):
		super().connectionLost(reason)

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

class ExternalProxyInternalProtocol(EWProtocol):
	"""
	Handles sending data as buffered "poems" from clients to the internal proxy and vice versa
	"""
	def packet_release_queue(self, buff):
		"""
		Allow client with packed uuid to send packets
		"""
		uuid = buff.unpack_uuid()
		client = self.other_factory.get_client(uuid)

		# Add queued packets to buffer
		for packet_uuid, packet_name, packet_data in client.queue:
			self.factory.input_buffer.append((uuid, packet_name, packet_data))

		client.queue = None # Remove queue

	def packet_mc_login_success(self, uuid, buff):
		"""
		Set protocol_mode to play
		https://wiki.vg/Protocol#Handshake
		"""
		client = self.other_factory.get_client(uuid)

		client.send_packet("login_success", buff.read()) # Send packet myself
		client.protocol_mode = "play" # Change mode after sending to prevent an error

		return (uuid, "login_success", None) # Prevent old packet from sending

class ExternalProxyInternalFactory(EWFactory, ReconnectingClientFactory):
	"""
	Quick and dirty hack to combine the ReconnectingClientFactory with the data of EWFactory
	"""
	def buildProtocol(self, addr):
		self.resetDelay() # Reset the reconnect delay
		return ExternalProxyInternalProtocol(self, self.buff_class, self.handle_direction, self.other_factory, self.buffer_wait)

def create(protocol_version, host, port, internal_host, internal_port, buffer_wait):
	"""
	Does two things:
	Creates an instance of ExternalProxyInternalFactory which communicates with the internal proxy
	Creates an instance of MCFactory with ExternalProxyBungeeCordFrontEndProtocol
	Args:
		protocol_version: protocol specification to use
		host: external proxy's listening ip
		port: external proxy's istening port
		internal_host: internal proxy's ip
		internal_port: internal proxy's port
		buffer_wait: amount of time to wait before sending buffered packets (in ms)
	"""
	# Create an instance of ExternalProxyInternalFactory which communicates with the internal proxy as a client
	internal_factory = ExternalProxyInternalFactory(protocol_version, "downstream", buffer_wait)

	# Create a MCFactory and assign it the ExternalProxyBungeeCordFrontEndProtocol which will handle packets
	server = MCFactory(protocol_version, "upstream")
	server.protocol = ExternalProxyBungeeCordFrontEndProtocol

	# Assign other_factory
	internal_factory.other_factory = server
	server.other_factory = internal_factory

	# Call reactor
	reactor.connectTCP(internal_host, internal_port, internal_factory)
	reactor.listenTCP(port, server, interface=host)
