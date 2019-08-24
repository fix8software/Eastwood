from quarry.net.protocol import BufferUnderrun
from queue import Queue
from twisted.internet import reactor

from eastwood.compressor_depressor import CompressorDepressor, OutboxHandlerThread
from eastwood.protocols.base_protocol import BaseProtocol
from eastwood.ew_packet import packet_ids, packet_names

# A bunch of variables that haven't become arguments.
COMP_THREADS = 1
DEP_THREADS = 1

class EWProtocol(BaseProtocol):
	"""
	Base class that contains shared functionality between the two proxy's comm protocols
	Data sent over is buffered and lz4 compressed
	"""
	def __init__(self, factory, buff_class, handle_direction, other_factory, buffer_wait):
		"""
		Protocol args:
			factory: factory that made this protocol (subclass of EWFactory)
			other_factory: the other factory that communicates with this protocol (in this case an instance of MCProtocol)
			buffer_wait: amount of time to wait before sending buffered packets (in ms)
		"""
		super().__init__(factory, buff_class, handle_direction, other_factory)
		self.buffer_wait = buffer_wait

		self.compressor_input_queue = Queue()
		self.compressor_output_queue = Queue()
		self.depressor_input_queue = Queue()
		self.depressor_output_queue = Queue()

		self.compression_index = 0 # Index for packet order
		self.compression_handler = OutboxHandlerThread(self.compressor_output_queue, reactor.callFromThread, self.send_packet, "poem")
		self.depression_index = 0 # Index for packet order
		self.decompression_handler = OutboxHandlerThread(self.depressor_output_queue, reactor.callFromThread, self.parse_packet_recv_poem)

		self.compressors = []
		for x in range(COMP_THREADS):
			self.compressors.append(CompressorDepressor(self.compressor_input_queue, self.compressor_output_queue, "compress"))

		self.depressors = []
		for x in range(DEP_THREADS):
			self.depressors.append(CompressorDepressor(self.depressor_input_queue, self.depressor_output_queue, "decompress"))

	def connectionMade(self):
		"""
		Called when a connection is made
		"""
		super().connectionMade()

		if self.factory.instance: # Only one protocol can exist
			self.transport.loseConnection()
			return

		self.factory.instance = self

		# Start compressor and depressor
		for x in self.compressors:
			x.start()
		for x in self.depressors:
			x.start()

		# Start handlers
		self.compression_handler.start()
		self.decompression_handler.start()

		# Run self.send_buffered_packets every self.buffer_wait ms
		reactor.callLater(self.buffer_wait/1000, self.send_buffered_packets)

	def connectionLost(self, reason):
		super().connectionLost(reason)

		# Remove factory instance
		self.factory.instance = None

		# Stop compressor and decompressor
		for x in self.compressors:
			x.running = False
			x.join()

		for x in self.depressors:
			x.running = False
			x.join()

		# Stop handlers
		self.compression_handler.running = False
		self.decompression_handler.running = False
		self.compression_handler.join()
		self.decompression_handler.join()

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

	def send_buffered_packets(self):
		"""
		Sends all packets in self.input_buffer to the other proxy as a poem
		"""
		# Schedule the next call
		reactor.callLater(self.buffer_wait/1000, self.send_buffered_packets)

		if len(self.factory.input_buffer) < 1: # Do not send empty packets
			return

		data = []
		for i in range(len(self.factory.input_buffer)): # Per packet info
			uuid, packet_name, packet_data = self.factory.input_buffer.popleft()
			buff = packet_data.buff # We don't use read because we need the entire buffer's data

			data.append(self.buff_class.pack_uuid(uuid)) # Pack uuid of client
			# TODO: Pass the id instead of the string name to save bandwidth?
			buff = self.buff_class.pack_string(packet_name) + buff # Prepend packet name to buffer
			data.append(self.buff_class.pack_packet(buff)) # Append buffer as packet

			packet_data.discard() # Buffer is no longer needed

		# Compress poem and send
		self.compressor_input_queue.put_nowait((self.compression_index, b"".join(data)))
		self.compression_index += 1 # Increment index

	def packet_recv_poem(self, buff):
		"""
		Uncompresses poem packet data
		"""
		# Decompress data
		self.depressor_input_queue.put_nowait((self.depression_index, buff.read()))
		self.depression_index += 1 # Increment index

	def parse_packet_recv_poem(self, uncompressed_data):
		"""
		Parses the poem and dispatches callouts with packet_mc_* callbacks
		Also forwards the packets afterwards
		"""
		buff = self.buff_class(uncompressed_data) # Create buffer

		data = []
		try:
			while True: # Unpack data until a bufferunderrun
				uuid = buff.unpack_uuid()
				packet = buff.unpack_packet(self.buff_class) # Packet is unpacked here as the subclass will just forward it
				packet_name = packet.unpack_string()
				packet.save()
				data.append((uuid, packet_name, packet))
		except BufferUnderrun:
			pass

		buff.discard() # Discard when done

		# Dispatch calls
		for uuid, packet_name, packet_data in data:
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
