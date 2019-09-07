"""
Twisted protocol and factory for TCP communication
"""

import logging
from quarry.net.protocol import BufferUnderrun
from twisted.internet.protocol import Protocol

class BaseProtocol(Protocol):
	"""
	Base class that contains shared functionality between all protocols in eastwood
	Much of the protocol code is borrowed from https://github.com/barneygale/quarry/blob/master/quarry/net/protocol.py
	"""
	def __init__(self, factory, buff_class, handle_direction, other_factory, config, modules=()):
		"""
		Protocol args:
			factory: factory that made this protocol (subclass of BaseFactory)
			buff_class: buffer class that this protocol will use
			handle_direction: direction packets being handled by this protocol are going (can be "clientbound" or "serverbound")
			other_factory: the other factory that this protocol will communicate with
			config: config dict
			modules: list of modules to use (priority is left to right)
		"""
		self.factory = factory
		self.other_factory = other_factory
		self.logger = logging.getLogger(name=self.__class__.__name__)
		self.logger.setLevel(logging.INFO)
		self.buff_class = buff_class
		self.config = config
		self.pers_buff = self.buff_class() # There is a persistant buffer to prevent dropping of incomplete packets

		# Determine handle and send direction based off one argument
		# Note: Send direction means that these packets are never touched by the protocol, just sent
		self.handle_direction = handle_direction
		if self.handle_direction == "upstream":
			self.send_direction = "downstream"
		elif self.handle_direction == "downstream":
			self.send_direction = "upstream"
		else:
			raise ValueError

		self.modules = [] # Module array
		self.create_modules(modules) # Initialize modules

		self.create() # Call create function

	def create(self):
		"""
		Skeleton init function so overriding __init__ is not necessary
		Can to be overriden
		"""

	def create_modules(self, modules):
		"""
		Initializes and registers modules
		Can be overriden (w/ a super) to prepend internal modules
		"""
		# Initialize modules
		for module in modules:
			self.modules.append(module(self))

	def connectionMade(self):
		"""
		Called when a connection is made
		"""
		self.recursive_dispatch("connectionMade")

	def connectionLost(self, reason):
		"""
		Called when the connection has been disconnected
		"""
		self.recursive_dispatch("connectionLost", reason)

	def dataReceived(self, data):
		"""
		Called by twisted when data is received over tcp by the protocol
		"""
		# Dump the data into the persistant buffer
		self.pers_buff.add(data)

		# Read sent packets in the buffer
		# Twisted may provide multiple packets in one dataRecieved call
		while True:
			self.pers_buff.save() # At this stage, the buffer has the cursor at the right position, save it

			try:
				buff = self.pers_buff.unpack_packet(self.buff_class)
			except BufferUnderrun:
				# The packet we are trying to unpack is incomplete!
				# Wait for the next dataRecieved to process packets
				self.pers_buff.restore() # Revert buffer to the good state
				break

			# Attempt to identify the packet
			try:
				id = buff.unpack_varint()
				name = self.get_packet_name(id) # The first datavalue in the packet is the identifier
			except ValueError:
				self.logger.info("Could not retrieve packet id")
				self.transport.loseConnection()
				return
			except KeyError:
				self.transport.loseConnection()
				return

			# Dispach the packet to packet handlers
			buff.save()
			try:
				self.packet_received(buff, name)
			except BufferUnderrun:
				self.logger.info("Packet is too short: {}".format(name))
				self.transport.loseConnection()
				return

	def dispatch(self, function_name, *args, **kwargs):
		"""
		Calls the packet function packet_{*lookup_args} in a module, and returns whether or not the call is successful
		"""
		for module in self.modules:
			# The module with the highest priority will handle the packet
			handler = getattr(module, function_name, None)
			if handler is not None:
				return handler(*args, **kwargs)

	def recursive_dispatch(self, function_name, *args, **kwargs):
		"""
		Recursively calls function "function_name", does not return anything as this is meant to be for callbacks
		"""
		for module in self.modules:
			handler = getattr(module, function_name, None)
			if handler is not None:
				handler(*args, **kwargs)

	def packet_received(self, buff, name):
		"""
		Dispatch a packet based off name
		"""
		self.dispatch("_".join(("packet", "recv", name)), buff)

	def send_packet(self, name, *data):
		"""
		Sends a mc packet to the remote
		"""
		data = b"".join(data) # Combine data
		data = self.buff_class.pack_varint(self.get_packet_id(name)) + data # Prepend packet ID
		data = self.buff_class.pack_packet(data) # Pack data as a packet

		self.transport.write(data) # Send

	def get_packet_name(self, id):
		"""
		Get packet name from id
		Meant to be overriden
		Args:
			id: id of the packet
		Returns:
			name: name of the packet
		"""

	def get_packet_id(self, name):
		"""
		Get packet name from id
		Meant to be overriden
		Args:
			name: name of the packet
		Returns:
			id: id of the packet
		"""
