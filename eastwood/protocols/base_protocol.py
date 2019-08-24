"""
Twisted protocol and factory for TCP communication
"""

import logging
from quarry.net.protocol import BufferUnderrun
from twisted.internet.protocol import Protocol

class PacketDispatcher:
	"""
	The one that comes with quarry is shit, ment to be a drop-in replacement
	"""
	def dispatch(self, lookup_args, *args, **kwargs):
		handler = getattr(self, "packet_{}".format("_".join(lookup_args)), None)
		if handler is not None:
			return handler(*args, **kwargs)

class BaseProtocol(Protocol, PacketDispatcher):
	"""
	Base class that contains shared functionality between all protocols in eastwood
	Much of the protocol code is borrowed from https://github.com/barneygale/quarry/blob/master/quarry/net/protocol.py
	"""
	def __init__(self, factory, buff_class, handle_direction, other_factory):
		"""
		Protocol args:
			factory: factory that made this protocol (subclass of BaseFactory)
			buff_class: buffer class that this protocol will use
			handle_direction: direction packets being handled by this protocol are going (can be "clientbound" or "serverbound")
			other_factory: the other factory that this protocol will communicate with
		"""
		self.factory = factory
		self.other_factory = other_factory
		self.logger = logging.getLogger(name=self.__class__.__name__)
		self.logger.setLevel(logging.INFO)
		self.buff_class = buff_class
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

	def connectionMade(self):
		"""
		Called when a connection is made
		"""
		self.logger.info("Connected to other proxy!")

	def connectionLost(self, reason):
		"""
		Called when the connection is properly disconnected
		"""
		self.logger.info("Lost connection to other proxy! Reason: {}".format(reason))

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

	def packet_received(self, buff, name):
		"""
		Dispatch a packet based off name
		"""
		if not self.dispatch(("recv", name), buff):
			self.packet_unhandled(buff, name)

	def packet_unhandled(self, buff, name):
		"""
		Called when a packet is not handled
		"""
		buff.discard()

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
