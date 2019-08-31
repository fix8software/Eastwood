from quarry.data.packets import packet_names, packet_idents
from quarry.types.uuid import UUID

from eastwood.protocols.base_protocol import BaseProtocol

class MCProtocol(BaseProtocol):
	"""
	Base protocol that communicates between the minecraft client and server
	Intercepts packets after being processed
	"""
	def create(self):
		self.protocol_version = self.config["global"]["protocol_version"]
		self.protocol_mode = "init"
		self.uuid = UUID.random() # UUID can be overriden

	def connectionMade(self):
		# Assign uuid to self
		self.factory.uuid_dict[self.uuid.to_hex()] = self

		# Call module handlers
		super().connectionMade()

	def connectionLost(self, reason):
		# Remove self from uuid dict
		del self.factory.uuid_dict[self.uuid.to_hex()]

		# Call module handlers
		super().connectionLost(reason)

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
