from collections import deque

from eastwood.factories.base_factory import BaseFactory
from eastwood.protocols.ew_protocol import EWProtocol

class EWFactory(BaseFactory):
	"""
	Derivative of Base factory that passes required args to EWProtocol
	"""
	protocol=EWProtocol

	def __init__(self, handle_direction, config):
		"""
		Args:
			handle_direction: direction packets being handled by this protocol are going (can be "clientbound" or "serverbound")
			config: config dict
		"""
		super().__init__(handle_direction, config)
		self.input_buffer = deque()
		self.instance = None # Only one protcol can exist in EWFactory
