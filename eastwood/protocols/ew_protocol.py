from collections import defaultdict
from quarry.net.protocol import BufferUnderrun
from twisted.internet import reactor

from eastwood.non_blocking_io import HandlerManager
from eastwood.plasma import ParallelAESInterface, ParallelCompressionInterface
from eastwood.protocols.base_protocol import BaseProtocol
from eastwood.ew_packet import packet_ids, packet_names

# A bunch of variables that haven't become arguments.
COMP_THREADS = 1
DEP_THREADS = 1
ENC_THREADS = 1
DEC_THREADS = 1

class EWProtocol(BaseProtocol):
	"""
	Base class that contains shared functionality between the two proxy's comm protocols
	Data sent over is buffered and lz4 compressed
	"""
	def __init__(self, factory, buff_class, handle_direction, other_factory, buffer_wait, password, secret):
		"""
		Protocol args:
			factory: factory that made this protocol (subclass of EWFactory)
			other_factory: the other factory that communicates with this protocol (in this case an instance of MCProtocol)
			buffer_wait: amount of time to wait before sending buffered packets (in ms)
			password: password to authenticate with
			secret: aes secret to use
		"""
		super().__init__(factory, buff_class, handle_direction, other_factory)
		self.buffer_wait = buffer_wait
		self.password = password # NOTE: Not used by EWProtocol, its subclasses will handle authentication with it

		self.compression_handler = HandlerManager(COMP_THREADS,
											ParallelCompressionInterface,
											"compress",
											reactor.callFromThread,
											callback_args=(self.send_packet, "poem")
											)
		self.depression_handler = HandlerManager(DEP_THREADS,
											ParallelCompressionInterface,
											"decompress",
											reactor.callFromThread,
											callback_args=(self.parse_packet_recv_poem,)
											)

		self.encryption_handler = HandlerManager(ENC_THREADS,
											ParallelAESInterface,
											"encrypt",
											reactor.callFromThread,
											callback_args=(self.parse_encrypted_packet,),
											plasma_args=(secret.encode(),)
											)
		self.decryption_handler = HandlerManager(DEC_THREADS,
											ParallelAESInterface,
											"decrypt",
											reactor.callFromThread,
											callback_args=(self.parse_decrypted_packet,),
											plasma_args=(secret.encode(),)
											)

	def connectionMade(self):
		"""
		Called when a connection is made
		"""
		super().connectionMade()

		if self.factory.instance: # Only one protocol can exist
			self.transport.loseConnection()
			return

		self.factory.instance = self

		# Start handlers
		self.encryption_handler.start()
		self.decryption_handler.start()
		self.compression_handler.start()
		self.depression_handler.start()

		# Run self.send_buffered_packets every self.buffer_wait ms
		reactor.callLater(self.buffer_wait/1000, self.send_buffered_packets)

	def connectionLost(self, reason):
		super().connectionLost(reason)

		# Remove factory instance
		self.factory.instance = None

		# Stop handlers
		self.encryption_handler.stop()
		self.decryption_handler.stop()
		self.compression_handler.stop()
		self.depression_handler.stop()

	def packet_received(self, buff, name):
		"""
		Decrypt the packets
		"""
		self.decryption_handler.add_to_queue(buff.read(), name)
		buff.discard()

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
		self.encryption_handler.add_to_queue(b"".join(data), name)

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

		poem = defaultdict(bytes) # Use default dict to keep track of packet data by name

		for i in range(len(self.factory.input_buffer)): # Per packet info
			uuid, packet_name, packet_data = self.factory.input_buffer.popleft()

			# TODO: Pass the id instead of the string name to save bandwidth?
			buff = self.buff_class.pack_string(packet_name) + packet_data.buff # Prepend packet name to buffer

			poem[packet_name] = b"".join([poem[packet_name],
									self.buff_class.pack_varint(i), # Pack index of packet
									self.buff_class.pack_uuid(uuid), # Pack uuid of client
									self.buff_class.pack_packet(buff) # Append buffer (as packet for length prefixing)
									])

			packet_data.discard() # Buffer is no longer needed

		# Compress poem and send
		self.compression_handler.add_to_queue(b"".join(poem.values()))

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
		buff = self.buff_class(uncompressed_data) # Create buffer

		unordered_data = {} # Holds packets by index
		try:
			while True: # Unpack data until a bufferunderrun
				index = buff.unpack_varint()
				uuid = buff.unpack_uuid()
				packet = buff.unpack_packet(self.buff_class) # Packet is unpacked here as the subclass will just forward it
				packet_name = packet.unpack_string()
				packet.save()
				unordered_data[index] = (uuid, packet_name, packet)
		except BufferUnderrun:
			pass

		buff.discard() # Discard when done

		# Dispatch calls
		for tup in sorted(unordered_data.items(), key=lambda kv: kv[0]):
			uuid, packet_name, packet_data = tup[1]

			try:
				client = self.other_factory.get_client(uuid) # Get client
			except KeyError:
				continue # The client has disconnected already, ignore

			try: # Attempt to dispatch
				new_packet = client.dispatch(("send", packet_name), packet_data)
			except BufferUnderrun:
				client.logger.info("Packet is too short: {}".format(packet_name))
				continue

			# If nothing was returned, the packet should be sent as it was originally
			if not new_packet:
				new_packet = (packet_name, packet_data)

			# Forward packet
			if new_packet[1] != None: # If the buffer is none, it was explictly stated to not send the packet!
				client.send_packet(new_packet[0], new_packet[1].buff)
