from collections import deque
from multiprocessing import JoinableQueue
from quarry.net.protocol import BufferUnderrun
from twisted.internet import reactor

from eastwood.compressor_depressor import Compressor, Depressor, OutboxHandlerThread
from eastwood.protocols.base_protocol import BaseFactory, BaseProtocol
from eastwood.ew_packet import packet_ids, packet_names

# A bunch of variables that haven't become arguments.
COMP_THREADS = 4
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

		self.compressor_input_queue = JoinableQueue()
		self.compressor_output_queue = JoinableQueue()
		self.depressor_input_queue = JoinableQueue()
		self.depressor_output_queue = JoinableQueue()

		self.compression_handler = OutboxHandlerThread(self.compressor_output_queue, reactor.callFromThread, self.send_data)
		self.decompression_handler = OutboxHandlerThread(self.depressor_output_queue, reactor.callFromThread, super().dataReceived)

		self.compressors = []
		for x in range(COMP_THREADS):
			self.compressors.append(Compressor(self.compressor_input_queue, self.compressor_output_queue))

		self.depressors = []
		for x in range(DEP_THREADS):
			self.depressors.append(Depressor(self.depressor_input_queue, self.depressor_output_queue))

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
			x.terminate()

		for x in self.depressors:
			x.terminate()

		try:
			self.compression_handler.kill()
			self.decompression_handler.kill()
		except:
			pass
	
		# Stop handlers
		self.compression_handler.running = False
		self.decompression_handler.running = False
		self.compression_handler.join()
		self.decompression_handler.join()

	def dataReceived(self, data):
		"""
		Called by twisted when data is received over tcp by the protocol
		"""
		self.depressor_input_queue.put_nowait(data)

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
		Sends a ew packet to the other proxy
		"""
		data = b"".join(data) # Combine data
		data = self.buff_class.pack_varint(self.get_packet_id(name)) + data # Prepend packet ID
		data = self.buff_class.pack_packet(data) # Pack data as a packet

		self.compressor_input_queue.put_nowait(data)

	def send_data(self, data):
		"""
		Callback for compressor
		"""
		self.transport.write(data)

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

		# Send poem
		self.send_packet("poem", *data)

	def packet_poem(self, buff):
		"""
		Parses the poem and dispatches callouts with packet_mc_* callbacks
		Also forwards the packets afterwards
		"""
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
		for packet in data:
			try:
				new_packet = self.dispatch(("mc", packet[1]), packet[0], packet[2])
			except BufferUnderrun:
				self.logger.info("Packet is too short: {}".format(packet[1]))
				continue

			# If nothing was returned, the packet should be sent as it was originally
			if not new_packet:
				new_packet = packet

			# Forward packet
			if new_packet[2] != None: # If the buffer is none, it was explictly stated to not send the packet!
				try:
					self.other_factory.get_client(new_packet[0]).send_packet(new_packet[1], new_packet[2].buff)
				except KeyError:
					# The client has disconnected already, ignore
					pass

class EWFactory(BaseFactory):
	"""
	Derivative of Base factory that passes required args to EWProtocol
	"""
	protocol=EWProtocol

	def __init__(self, protocol_version, handle_direction, buffer_wait):
		"""
		Args:
			protocol_version: minecraft protocol specification to use
			handle_direction: direction packets being handled by this protocol are going (can be "clientbound" or "serverbound")
			buffer_wait: amount of time to wait before sending buffered packets (in ms)
		"""
		super().__init__(protocol_version, handle_direction)
		self.input_buffer = deque()
		self.buffer_wait = buffer_wait
		self.instance = None # Only one protcol can exist in EWFactory

	def buildProtocol(self, addr):
		return self.protocol(self, self.buff_class, self.handle_direction, self.other_factory, self.buffer_wait)
