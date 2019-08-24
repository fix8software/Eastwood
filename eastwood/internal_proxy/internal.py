from eastwood.factories.ew_factory import EWFactory
from eastwood.protocols.ew_protocol import EWProtocol

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
