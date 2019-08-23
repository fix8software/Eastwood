"""
Threaded classes which offload the work of compression and decompression from EWProtocol and its subclasses
"""
import logging
from queue import Empty
from threading import Thread

from eastwood.plasma import ParallelCompressionInterface

class OutboxHandlerThread(Thread):
	"""
	Threaded class that handles data from queues
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
		self.daemon = True

		self.running = True # Controls the loop

		self.logger = logging.getLogger(name=self.__class__.__name__)
		self.logger.setLevel(logging.INFO)

		self.callback = callback
		self.callback_args = args
		self.callback_kwargs = kwargs

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
					break # Packet is still being processed, wait for next get

				# Save Our Ram
				del self.wait_list[self.index]

				if patient[1]:
					self.run_callback(patient[1]) # Send it
				self.index += 1 # Increment index

			self.queue.task_done()

	def run_callback(self, *args, **kwargs):
		"""
		Runs the callback with the provided callback args and kwargs
		"""
		self.callback(*self.callback_args, *args, **self.callback_kwargs, **kwargs)

class CompressorDepressor(Thread):
	"""
	Threaded class that either compresses or decompresses data from queues
	"""
	def __init__(self, input_queue, output_queue, handle_mode):
		"""
		Args:
			input_queue: queue to use for input (accepts tuple of index, data)
			output_queue: queue to output to
			handle_mode: method to handle data, either "compress" or "decompress"
		"""
		super().__init__()
		self.daemon = True

		self.running = True # Controls the loop

		self.logger = logging.getLogger(name=self.__class__.__name__)
		self.logger.setLevel(logging.INFO)

		self.input_queue = input_queue # Compression/decompression queue
		self.output_queue = output_queue # Sent to the handler

		# Plasma instance
		self.plasma = ParallelCompressionInterface()
		if handle_mode == "compress":
			self.handle_func = self.plasma.compress
		elif handle_mode == "decompress":
			self.handle_func = self.plasma.decompress
		else:
			raise ValueError

	def run(self):
		while self.running:
			try:
				packet_tuple = self.input_queue.get(timeout=1)
			except Empty:
				continue

			new_data = self.handle_func(packet_tuple[1])
			self.output_queue.put_nowait((packet_tuple[0], new_data))
			self.input_queue.task_done()
