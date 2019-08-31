from quarry.types.buffer import buff_types
from twisted.internet.protocol import Factory

from eastwood.protocols.base_protocol import BaseProtocol

class BaseFactory(Factory):
	"""
	Base Factory, contains some common variables and passes needed arguments for BaseProtocol
	"""
	protocol=BaseProtocol

	def __init__(self, handle_direction, config):
		"""
		Args:
			handle_direction: direction packets being handled by this protocol are going (can be "clientbound" or "serverbound")
			config: config dict
		"""
		self.config = config
		self.protocol_version = config["global"]["protocol_version"]
		self.buff_class = self.get_buff_class()
		self.handle_direction = handle_direction
		self.other_factory = None # Other factory is assigned by hand to prevent chicken egg problem

	def get_buff_class(self):
		for version, buff_class in reversed(buff_types):
			if self.protocol_version >= version:
				return buff_class

	def buildProtocol(self, addr):
		return self.protocol(self, self.buff_class, self.handle_direction, self.other_factory, self.config)
