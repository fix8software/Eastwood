"""
Threaded classes which offload the work of compression and decompression from EWProtocol and its subclasses
"""
import logging
import lzma
from multiprocessing import Process
from queue import Empty
from threading import Thread

# A bunch of variables that haven't become arguments.
# Designed to control how data is transmitted between EP and IP, which
# means that both the IP and EP must have equal configurations.
COMPRESSION_LEVEL = 0
COMPRESSION_FILTERS = [
	#{"id": lzma.FILTER_DELTA, "dist": 1},
    {"id": lzma.FILTER_LZMA2, "preset": COMPRESSION_LEVEL},
]

class OutboxHandlerThread(Thread):
	"""
	Threaded class that handles data from multiprocess queues
	"""
	def __init__(self, queue, callback, *args, **kwargs):
		"""
		Args:
			queue: outbox queue to handle data from (accepts tuple of index, data)
			callback: callback to run after handling data
			*args: args to prepend to callback
			**kwargs: kwargs to append to callback
		"""
		super().__init__()

		self.callback = callback
		self.callback_args = args
		self.callback_kwargs = kwargs
		self.logger = logging.getLogger(name=self.__class__.__name__)
		self.logger.setLevel(logging.INFO)
		self.daemon = True
		self.running = True # Controls the loop
		self.queue = queue # Outbound queue
		self.wait_list = {} # Packets waiting for other packets to process
		self.index = 0 # Current index (index of last packet processed)

	def run(self):
		while self.running:
			try:
				packet_tuple = self.queue.get(timeout=1)
			except Empty:
				continue

			if packet_tuple[0] != self.index:
				# Packet is supposed to be sent after one being processed
				self.wait_list[packet_tuple[0]] = packet_tuple
				return

			# Packet is next to be sent
			if packet_tuple[1]:
				self.run_callback(packet_tuple[1]) # Send it
			self.index += 1 # Increment index

			# Send packets that were waiting for this packet
			while True:
				try:
					patient = self.wait_list[self.index]
				except KeyError:
					return # Packet is still being processed, wait for next get

				# Save Our Ram
				del self.wait_list[self.index]

				if patient[1]:
					self.run_callback(patient[1]) # Send it
				self.index += 1 # Increment index

	def run_callback(self, *args, **kwargs):
		"""
		Runs the callback with the provided callback args and kwargs
		"""
		self.callback(*self.callback_args, *args, **self.callback_kwargs, **kwargs)

class BaseCompressionProcess(Process):
	"""
	Base class to prevent dry code
	"""
	def __init__(self, input_queue, output_queue):
		"""
		Args:
			input_queue: queue to use for input (accepts tuple of index, data)
			output_queue: queue to output to
		"""
		super().__init__()

		self.logger = logging.getLogger(name=self.__class__.__name__)
		self.logger.setLevel(logging.INFO)
		self.daemon = True
		self.input_queue = input_queue # Compression/decompression queue
		self.output_queue = output_queue # Sent to the handler

	def run(self):
		while True:
			try:
				packet_tuple = self.input_queue.get(timeout=1)
			except Empty:
				continue

			new_data = self.handle_data(packet_tuple[1])
			self.output_queue.put_nowait((packet_tuple[0], new_data))

	def handle_data(self, data):
		"""
		Logic to handle data popped from queue
		Meant to be overriden
		"""
		pass

class Compressor(BaseCompressionProcess):
	def __init__(self, input_queue, output_queue):
		"""
		Args:
			input_queue: queue to use for input (accepts tuple of index, data)
			output_queue: queue to output to
		"""
		super().__init__(input_queue, output_queue)

		self.compressor_rcyl = (lambda x: lzma.compress(x, format=lzma.FORMAT_RAW, filters=COMPRESSION_FILTERS))

	def handle_data(self, data):
		# LZMA compress data
		try:
			return self.compressor_rcyl(data)
		except lzma.LZMAError:
			self.logger.warn("Failed to lzma compress packet!")

class Depressor(BaseCompressionProcess):
	def __init__(self, input_queue, output_queue):
		"""
		Args:
			input_queue: queue to use for input (accepts tuple of index, data)
			output_queue: queue to output to
		"""
		super().__init__(input_queue, output_queue)

		self.decompressor_rcyl = (lambda: lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=COMPRESSION_FILTERS))
		self.decompressor = self.decompressor_rcyl() # LZMA provides an internal buffer incase incomplete packets are sent

	def handle_data(self, data):
		# LZMA uncompress data
		uncompressed_data = b""
		while True:
			try:
				uncompressed_data += self.decompressor.decompress(data)
			except lzma.LZMAError:
				self.logger.warn("Failed to lzma decompress packet!")
				return

			if self.decompressor.eof: # eof is reached, create a new decompressor
				data = self.decompressor.unused_data # reuse old data in another call
				self.decompressor = self.decompressor_rcyl() # New decompressor
				continue # Now uncompress unused data

			return uncompressed_data # Returned already decompressed data
