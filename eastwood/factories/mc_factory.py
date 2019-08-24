from eastwood.protocols.base_protocol import BaseFactory
from eastwood.protocols.mc_protocol import MCProtocol

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
