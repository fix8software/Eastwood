from quarry.net.protocol import BufferUnderrun
from twisted.internet import reactor

from eastwood.modules import Module
from eastwood.non_blocking_io import HandlerManager
from eastwood.plasma import ParallelAESInterface, ParallelCompressionInterface
from eastwood.protocols.base_protocol import BaseProtocol
from eastwood.ew_packet import packet_ids, packet_names

class EWModule(Module):
	"""
	Internal module that deals with peom compression/decompression
	"""
	def __init__(self, protocol):
		super().__init__(protocol)

		self.compression_handler = HandlerManager(1,
											ParallelCompressionInterface,
											"compress",
											reactor.callFromThread,
											callback_args=(self.protocol.send_packet, "poem")
											)
		self.depression_handler = HandlerManager(1,
											ParallelCompressionInterface,
											"decompress",
											reactor.callFromThread,
											callback_args=(self.parse_packet_recv_poem,)
											)

	def connectionMade(self):
		self.compression_handler.start()
		self.depression_handler.start()

	def connectionLost(self, reason):
		self.compression_handler.stop()
		self.depression_handler.stop()

	def compress_and_send(self, data):
		self.compression_handler.add_to_queue(data)

	def packet_recv_poem(self, buff):
		"""
		Uncompresses poem packet data
		"""
		self.depression_handler.add_to_queue(buff.read())

	def parse_packet_recv_poem(self, uncompressed_data):
		"""
		Parses the poem and dispatches callouts with packet_mc_* callbacks
		Also forwards the packets afterwards
		"""
		buff = self.protocol.buff_class(uncompressed_data) # Create buffer

		try:
			while True: # Unpack data until a bufferunderrun
				uuid = buff.unpack_uuid()
				packet = buff.unpack_packet(self.protocol.buff_class) # Packet is unpacked here as the subclass will just forward it
				packet_name = packet.unpack_string()
				packet.save()

				try:
					client = self.protocol.other_factory.get_client(uuid) # Get client
				except KeyError:
					continue # The client has disconnected already, ignore

				try: # Attempt to dispatch
					new_packet = client.dispatch("_".join(("packet", "send", packet_name)), packet)
				except BufferUnderrun:
					client.logger.info("Packet is too short: {}".format(packet_name))
					continue

				# If nothing was returned, the packet should be sent as it was originally
				if not new_packet:
					new_packet = (packet_name, packet)

				# Forward packet
				if new_packet[1] != None: # If the buffer is none, it was explictly stated to not send the packet!
					client.send_packet(new_packet[0], new_packet[1].buff)
		except BufferUnderrun:
			pass

		buff.discard() # Discard when done

class EWProtocol(BaseProtocol):
	"""
	Base class that contains shared functionality between the two proxy's comm protocols
	Data sent over is buffered and compressed
	"""
	def create(self):
		self.buffer_wait = self.config["global"]["buffer_ms"]
		self.password = self.config["global"]["password"] # NOTE: Not used by EWProtocol, its subclasses will handle authentication with it
		self.secret = self.config["global"]["secret"]

		if self.secret: # Secret can be falsy (empty string)
			self.encryption_handler = HandlerManager(1,
												ParallelAESInterface,
												"encrypt",
												reactor.callFromThread,
												callback_args=(self.parse_encrypted_packet,),
												plasma_args=(self.secret.encode(),)
												)
			self.decryption_handler = HandlerManager(1,
												ParallelAESInterface,
												"decrypt",
												reactor.callFromThread,
												callback_args=(self.parse_decrypted_packet,),
												plasma_args=(self.secret.encode(),)
												)

	def create_modules(self, modules):
		super().create_modules((EWModule,) + modules) # Prepend ew module (poem parsing)

	def connectionMade(self):
		"""
		Called when a connection is made
		"""
		self.logger.info("Connected to other proxy!")

		if self.factory.instance: # Only one protocol can exist
			self.transport.loseConnection()
			return

		self.factory.instance = self

		# Start handlers
		if self.secret:
			self.encryption_handler.start()
			self.decryption_handler.start()

		# Run self.send_buffered_packets every self.buffer_wait ms
		reactor.callLater(self.buffer_wait/1000, self.send_buffered_packets)

		# Call module handlers
		super().connectionMade()

	def connectionLost(self, reason):
		"""
		Called when the proxy is properly disconnected
		"""
		self.logger.info("Lost connection to other proxy! Reason: {}".format(reason))

		# Remove factory instance
		self.factory.instance = None

		# Stop handlers
		if self.secret:
			self.encryption_handler.stop()
			self.decryption_handler.stop()

		# Call module handlers
		super().connectionLost(reason)

	def packet_received(self, buff, name):
		"""
		Decrypt the packets
		"""
		if self.secret:
			self.decryption_handler.add_to_queue(buff.read(), name)
			buff.discard()
		else:
			super().packet_received(buff, name)

	def parse_decrypted_packet(self, data, name):
		"""
		Pass to super with the right argument order
		Lambdas don't like supers :(
		"""
		super().packet_received(self.buff_class(data), name)

	def get_packet_name(self, id):
		"""
		Get packet name from id
		Meant to be overriden
		Args:
			id: id of the packet
		Returns:
			name: name of the packet
		"""
		try:
			info = packet_names[id]
		except KeyError:
			self.logger.error("No packet with id: {}".format(id))
			raise KeyError

		if self.handle_direction not in info[1]:
			self.logger.error("Wrong direction for packet id: {}".format(id))
			raise KeyError

		return info[0]

	def get_packet_id(self, name):
		"""
		Get packet name from id
		Meant to be overriden
		Args:
			name: name of the packet
		Returns:
			id: id of the packet
		"""
		try:
			info = packet_ids[name]
		except KeyError:
			self.logger.error("No packet with name: {}".format(name))
			raise KeyError

		if self.send_direction not in info[1]:
			self.logger.error("Wrong direction for packet name: {}".format(name))
			raise KeyError

		return info[0]

	def send_packet(self, name, *data):
		"""
		Encrypts packet before sending it
		"""
		if self.secret:
			self.encryption_handler.add_to_queue(b"".join(data), name)
		else:
			super().send_packet(name, *data)

	def parse_encrypted_packet(self, data, name):
		"""
		Pass to super with the right argument order
		Lambdas don't like supers :(
		"""
		super().send_packet(name, data)

	def send_buffered_packets(self):
		"""
		Sends all packets in self.input_buffer to the other proxy as a poem
		"""
		# Schedule the next call
		reactor.callLater(self.buffer_wait/1000, self.send_buffered_packets)

		if len(self.factory.input_buffer) < 1: # Do not send empty packets
			return

		poem = []
		for i in range(len(self.factory.input_buffer)): # Per packet info
			uuid, packet_name, packet_data = self.factory.input_buffer.popleft()

			# TODO: Pass the id instead of the string name to save bandwidth?
			buff = self.buff_class.pack_string(packet_name) + packet_data.buff # Prepend packet name to buffer

			poem.append(self.buff_class.pack_uuid(uuid)) # Pack uuid of client
			poem.append(self.buff_class.pack_packet(buff)) # Append buffer (as packet for length prefixing)

			packet_data.discard() # Buffer is no longer needed

		# Compress poem and send
		self.dispatch("compress_and_send", b"".join(poem))
