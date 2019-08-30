from collections import deque

from eastwood.factories.base_factory import BaseFactory
from eastwood.protocols.ew_protocol import EWProtocol

class EWFactory(BaseFactory):
	"""
	Derivative of Base factory that passes required args to EWProtocol
	"""
	protocol=EWProtocol

	def __init__(self, protocol_version, handle_direction, buffer_wait, password, secret):
		"""
		Args:
			protocol_version: minecraft protocol specification to use
			handle_direction: direction packets being handled by this protocol are going (can be "clientbound" or "serverbound")
			buffer_wait: amount of time to wait before sending buffered packets (in ms)
			password: password to authenticate with
			secret: aes secret to use
		"""
		super().__init__(protocol_version, handle_direction)
		self.input_buffer = deque()
		self.buffer_wait = buffer_wait
		self.password = password
		self.secret = secret
		self.instance = None # Only one protcol can exist in EWFactory

	def buildProtocol(self, addr):
		return self.protocol(self, self.buff_class, self.handle_direction, self.other_factory, self.buffer_wait, self.password, self.secret)
