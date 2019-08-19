from quarry.data.packets import packet_names, packet_idents
from quarry.types.uuid import UUID

from eastwood.protocols.base_protocol import BaseFactory, BaseProtocol

class MCProtocol(BaseProtocol):
	"""
	Base protocol that communicates between the minecraft client and server
	Intercepts packets after being processed
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
		super().__init__(factory, buff_class, handle_direction, other_factory)
		self.protocol_version = protocol_version
		self.protocol_mode = "init"
		self.uuid = uuid or UUID.random()

	def connectionMade(self):
		# Assign uuid to self
		self.factory.uuid_dict[self.uuid.to_hex()] = self

	def connectionLost(self, reason):
		# Remove self from uuid dict
		del self.factory.uuid_dict[self.uuid.to_hex()]

	def packet_received(self, buff, name):
		"""
		Packets are intercepted after going through the proxy's protocol hooks
		"""
		super().packet_received(buff, name)

		# Intercept packet here
		# Append it to the buffer list
		self.other_factory.input_buffer.append((self.uuid, name, buff))

	def packet_unhandled(self, buff, name):
		"""
		Default implementation is to discard packets, don't do that
		ExternalProxyInternalProtocol will discard the packets
		"""
		pass

	def get_packet_name(self, id):
		"""
		attempts to return packet name from id
		args:
			id: id of packet
		returns:
			name: name of packet
		"""
		key = (self.protocol_version, self.protocol_mode, self.handle_direction, id)
		try:
			return packet_names[key]
		except KeyError:
			self.logger.warn("No known packet: {}".format(key))
			raise KeyError

	def get_packet_id(self, name):
		"""
		attempts to return packet id from name
		args:
			name: name of packet
		returns:
			id: id of packet
		"""
		key = (self.protocol_version, self.protocol_mode, self.send_direction, name)
		try:
			return packet_idents[key]
		except KeyError:
			self.logger.warn("No known packet: {}".format(key))
			raise KeyError

class MCFactory(BaseFactory):
	"""
	Manages minecraft connections and also keeps track of their identity
	"""
	protocol=MCProtocol

	def __init__(self, protocol_version, handle_direction):
		"""
		Args:
			protocol_version: minecraft protocol specification to use
			handle_direction: direction packets being handled by this protocol are going (can be "clientbound" or "serverbound")
		"""
		super().__init__(protocol_version, handle_direction)
		self.uuid_dict = {} # Lookup for connection protocols by uuid

	def get_client(self, uuid):
		"""
		Gets a client
		Args:
			uuid: unique id of client
		Returns:
			protocol: protocol of client
		"""
		return self.uuid_dict[uuid.to_hex()]

	def buildProtocol(self, addr):
		return self.protocol(self, self.buff_class, self.handle_direction, self.other_factory, self.protocol_version)
