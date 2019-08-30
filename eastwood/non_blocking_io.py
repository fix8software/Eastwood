"""
Threaded classes which offload the work of blocking data handling from EWProtocol and its subclasses
"""
import logging
from queue import Empty, Queue
from threading import Thread

class HandlerManager:
	"""
	Class that manages handler threads
	"""
	def __init__(self, num_threads, plasma, plasma_func, callback, plasma_args=(), plasma_kwargs={}, callback_args=(), callback_kwargs={}):
		"""
		Args:
			num_threads: number of threads to use
			plasma: plasma interface to use
			plasma_func: name of function from plasma to handle data with
			callback: callback to run after handling data
			plasma_args: args for plasma
			plasma_kwargs: kwargs for plasma
			callback_args: args to prepend to callback
			callback_kwargs: kwargs to prepend to callback
		"""
		self.__index = 0 # Index for packet order
		self.__input_queue = Queue() # Data should be added via add_to_queue instead
		self.__output_queue = Queue() # Used by internal outbox handler only

		# Spawn workers
		self.__inbox_threads = []
		for i in range(num_threads):
			self.__inbox_threads.append(InboxHandlerThread(self.__input_queue, self.__output_queue, plasma, plasma_func, *plasma_args, **plasma_kwargs))

		# Spawn outbox handler thread
		self.__outbox_handler = OutboxHandlerThread(self.__output_queue, callback, *callback_args, **callback_kwargs)

	def start(self):
		"""
		Start managed threads
		"""
		# Start workers
		for thread in self.__inbox_threads:
			thread.start()

		# Start outbox handler
		self.__outbox_handler.start()

	def add_to_queue(self, data, *args, **kwargs):
		"""
		Adds data to queue, will be put into a tuple and prepended with an index
		Args:
			data: data to add
			*args: args to be passed to the callback
			**kwargs: kwargs to be passed to the callback
		"""
		self.__input_queue.put_nowait((self.__index, data, args, kwargs))
		self.__index += 1 # Increment index

	def stop(self):
		"""
		Stop managed threads, will block until completed
		"""
		# Stop workers
		for thread in self.__inbox_threads:
			thread.running = False
			thread.join()

		# Stop outbox handler
		self.__outbox_handler.running = False
		self.__outbox_handler.join()

class OutboxHandlerThread(Thread):
	"""
	Threaded class that handles data from queues
	"""
	def __init__(self, queue, callback, *args, **kwargs):
		"""
		Args:
			queue: outbox queue to handle data from (accepts tuple of index, data, args, kwargs)
			callback: callback to run after handling data
			*args: args to prepend to callback
			**kwargs: kwargs to prepend to callback
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
				self.run_callback(packet_tuple[1], *packet_tuple[2], **packet_tuple[3]) # Send it
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
					self.run_callback(patient[1], *patient[2], **patient[3]) # Send it
				self.index += 1 # Increment index

			self.queue.task_done()

	def run_callback(self, *args, **kwargs):
		"""
		Runs the callback with the provided callback args and kwargs
		"""
		self.callback(*self.callback_args, *args, **self.callback_kwargs, **kwargs)

class InboxHandlerThread(Thread):
	"""
	Threaded class handles data from an input queue
	"""
	def __init__(self, input_queue, output_queue, plasma, func_name, *args, **kwargs):
		"""
		Args:
			input_queue: queue to use for input (accepts tuple of index, data, args, kwargs)
			output_queue: queue to output to
			plasma: plasma interface to use
			func_name: name of function from plasma to handle data with
			*args: args for plasma
			**kwargs: kwargs for plasma
		"""
		super().__init__()
		self.daemon = True

		self.running = True # Controls the loop

		self.logger = logging.getLogger(name=self.__class__.__name__)
		self.logger.setLevel(logging.INFO)

		self.input_queue = input_queue # Input queue
		self.output_queue = output_queue # Output queue

		self.plasma = plasma(*args, **kwargs) # Plasma instance
		self.handle_func = getattr(self.plasma, func_name)

	def run(self):
		while self.running:
			try:
				packet_tuple = self.input_queue.get(timeout=1)
			except Empty:
				continue

			try: # Ignore packet if there are *any* errors
				new_data = self.handle_func(packet_tuple[1])
			except:
				self.logger.warn("Packet Index #{} thrown out!".format(packet_tuple[0]))
				new_data = None

			self.output_queue.put_nowait((packet_tuple[0], new_data, packet_tuple[2], packet_tuple[3]))
			self.input_queue.task_done()
