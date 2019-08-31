from eastwood.factories.base_factory import BaseFactory
from eastwood.protocols.mc_protocol import MCProtocol

class MCFactory(BaseFactory):
	"""
	Manages minecraft connections and also keeps track of their identity
	"""
	protocol=MCProtocol

	def __init__(self, handle_direction, config):
		"""
		Args:
			handle_direction: direction packets being handled by this protocol are going (can be "clientbound" or "serverbound")
			config: config dict
		"""
		super().__init__(handle_direction, config)
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
