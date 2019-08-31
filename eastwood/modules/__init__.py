import logging

class Module:
	"""
	*Documented* interface for handling packets being sent/recved from either EWProtocol or MCProtocol
	"""
	def __init__(self, protocol):
		"""
		Args:
			protocol: Protocol associated with this class
		"""
		self.protocol = protocol # Protocol that spawned this, usually EWProtocol or MCProtocol

		# Modules have their own logger you should use
		self.logger = logging.getLogger(name=self.__class__.__name__)
		self.logger.setLevel(logging.INFO)
		self.logger.debug("Initialized!")

	# CALLBACKS:
	# Callbacks will always be called, regardless of whether or not the module is the top one
	def connectionMade(self):
		"""
		Called when the protocol has connected
		Can be overriden
		"""

	def connectionLost(self, reason):
		"""
		Called when the protocol has been disconnected
		Can be overriden
		"""

	# READ THIS:
	# Packet Handlers are functions with the name packet_{send/recv}_{packet_name}
	# They recieve a Buffer object named buff containing packet data
	# They can read, send, and manipulate packets
	# The function can return a tuple of ("{packet_name}", {packet_data}), which will replace the packet being sent
	# The function can also return none as the {packet_data} to prevent the packet being sent
	# Otherwise, the protocol will send the original packet
	# Packet handlers are only called if the module is the top one that implements the handler
	#
	# For example:
	# 	def packet_recv_login_success(self, buff):
	#		"""
	# 		Switches the protocol's protocol mode to play
	#		"""
	#		self.protocol.protocol_mode = "play"
	#
	#		# There is no return statement, meaning that the original packet will be sent
