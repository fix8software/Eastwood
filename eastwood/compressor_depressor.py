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
			queue: outbox queue to handle data from
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

	def run(self):
		while self.running:
			try:
				data = self.queue.get(timeout=1)
			except Empty:
				continue

			self.run_callback(data)
			self.queue.task_done()

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
			input_queue: queue to use for input
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
				data = self.input_queue.get(timeout=1)
			except Empty:
				continue

			modified_data = self.handle_data(data)
			if modified_data:
				self.output_queue.put_nowait(modified_data)
			self.input_queue.task_done()

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
			input_queue: queue to use for input
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
			input_queue: queue to use for input
			output_queue: queue to output to
		"""
		super().__init__(input_queue, output_queue)

		self.decompressor_rcyl = (lambda: lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=COMPRESSION_FILTERS))
		self.decompressor = self.decompressor_rcyl() # LZMA provides an internal buffer incase incomplete packets are sent

	def handle_data(self, data):
		# LZMA uncompress data
		try:
			uncompressed_data = self.decompressor.decompress(data)
		except lzma.LZMAError:
			self.logger.warn("Failed to lzma decompress packet!")
			return # Ignore packet

		if self.decompressor.eof: # eof is reached, create a new decompressor
			unused_data = self.decompressor.unused_data # reuse old data in another call
			self.decompressor = self.decompressor_rcyl() # New decompressor
			self.output_queue.put_nowait(uncompressed_data) # Release already uncompressed data
			self.handle_data(unused_data) # Now uncompress unused data
			return

		return uncompressed_data
