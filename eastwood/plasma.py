"""
P L A S M A

Naphtha's library for parallel, timed operations such as Compression
and Encryption.
"""
from Crypto import Random
from Crypto.Cipher import AES
from psutil import cpu_count
from multiprocessing.pool import ThreadPool
from threading import Thread
import zstd, time, os, hashlib

# These are the only classes that ought to be used with Plasma publicly.
__all__ = ["ParallelAESInterface", "ParallelCompressionInterface"]

# These variables are the ones that probably won't break anything if you change them.
# Please note that these values must be the same for both the compressor and decompressor.
SIZE_BYTES = 3
META_BYTES = 1
BYTE_ORDER = 'little'

class ParallelCompressionInterface(object):
	# zstd attributes
	__MAX_LEVEL = 22
	__MIN_LEVEL = 1
	__BUFFER_TIME_MS = 10
	__TOO_LOW_MAX = 8
	__UNLEARN_INTERVAL_SECONDS = 180
	__ATHS_START = 0x003FFFFF
	
	"""
	Non-threadsafe class that automatically spawns processes for continued use.
	"""
	def __init__(self, nodes: int = cpu_count(), target_speed_ms: int = 20):
		"""
		Args:
			nodes: integer, amount of processes to spawn. Usually, you should use the default value.
		"""

		self.__too_low_tries = 0
		self.__big_data = b''
		self.__global_level = self.__MAX_LEVEL
		self.__pool = ThreadPool(nodes)
		self.__internal_node_count = nodes
		self.__average_time = 0
		self.__target_speed = target_speed_ms
		self.__average_too_high_size = self.__ATHS_START
		self.__unlearn_setback = self.__jitter_setback_training()
		self.__average_too_high_size = self.__ATHS_START
		
		self.__threads = []
		
		self.__threads.append(Thread(target=self.__jitter_training_reinitialization_thread))
		self.__threads[-1].daemon = True
		self.__threads[-1].start()
		
		self.last_level = self.__global_level
		
	def __jitter_setback_training(self) -> int:
		increment = (2 ** 16) - 1
		speed = 0
		size = increment
		while speed < self.__target_speed * 3:
			for _ in range(2):
				data = os.urandom(int(size / 2)) + (b'\x00' * int(size / 2))
				st = time.time()
				__ = self.compress(data, self.__MAX_LEVEL)
				speed = (time.time() - st) * 1000
				size += increment
		return size
		
	def __jitter_training_reinitialization_thread(self):
		while True:
			start = time.time()
			_ = self.compress(self.__big_data, self.__global_level)
			timed = (time.time() - start) * 1000
			
			if timed < self.__target_speed:
				self.__average_too_high_size = self.__unlearn_setback
			time.sleep(self.__UNLEARN_INTERVAL_SECONDS)

	@staticmethod
	def __level_arguments(chunk: bytes, level: int) -> tuple:
		"""
		Private function to automatically prepare arguments for internal compression.
		"""
		return (chunk, level)

	@staticmethod
	def __chunks(l, n):
		"""
		Quickest way to break up compression data into multiple chunks of bytes.
		"""
		for i in range(0, len(l), n):
			yield l[i:i+n]

	@staticmethod
	def __int_in(i: int, s: int = META_BYTES):
		return i.to_bytes(s, byteorder=BYTE_ORDER)

	@staticmethod
	def __int_out(i: bytes):
		return int.from_bytes(i, byteorder=BYTE_ORDER)

	def compress(self, input: bytes, level: int = -1) -> bytes:
		"""
		Main compression function.
		Args:
			input: Bytes to compress
			level: Compression level
			chunks: Chunks to compress with
		"""

		if level < 1:
			suggested = (lambda x,l,u: l if x<l else u if x>u else x)((lambda x,a,b,c,d: (x-a)/(b-a)*(d-c)+c)(len(input),0,self.__average_too_high_size,self.__MAX_LEVEL,self.__MIN_LEVEL),self.__MIN_LEVEL,self.__MAX_LEVEL)
			level = int((self.__global_level + suggested) // 2)

		startt = time.time()
		chunks = list(self.__chunks(input, (lambda x: x if x != 0 else 1)(int(round(len(input) / self.__internal_node_count)))))
		chunks = self.__pool.map(self.__internal_compression, [self.__level_arguments(c, level) for c in chunks])
		result = b''.join(chunks)
		
		msec = ((time.time() - startt) * 1000)
		self.__average_time = (self.__average_time + msec) / 2
		if self.__average_time > self.__target_speed and self.__global_level > self.__MIN_LEVEL:
			self.__global_level -= 1
		elif self.__average_time < self.__target_speed - self.__BUFFER_TIME_MS and self.__global_level < self.__MAX_LEVEL:
			self.__too_low_tries += 1
			if self.__too_low_tries >= self.__TOO_LOW_MAX:
				self.__global_level += 1
				self.__too_low_tries = 0
				
		if msec > self.__target_speed:
			self.__average_too_high_size = (self.__average_too_high_size + len(input)) // 2
			self.__big_data = input

		if len(result) > len(input):
			meta = self.__int_in(0b00000000)
			result = input
		else:
			meta = self.__int_in(0b00000001)

		self.last_level = level
		return meta + result

	def decompress(self, input: bytes) -> bytes:
		"""
		Main decompression function.
		Args:
			input: Bytes to decompress - Note this is not compatible with the output of the standard compression function.
		"""

		if self.__int_out(input[:META_BYTES]) == 0b00000000:
			return input[META_BYTES:]
		else:
			input = input[META_BYTES:]

		chunks = []
		while len(input) > 0:
			chunk_length = int.from_bytes(input[:SIZE_BYTES], byteorder=BYTE_ORDER)
			chunks.append(input[SIZE_BYTES:SIZE_BYTES+chunk_length])
			input = input[SIZE_BYTES+chunk_length:]

		return b''.join(self.__pool.map(self.__internal_decompression, chunks))

	@staticmethod
	def __compress(input: bytes, level: int = 6) -> bytes:
		return zstd.compress(input, level)

	@staticmethod
	def __decompress(input: bytes) -> bytes:
		return zstd.decompress(input)

	def __internal_compression(self, args) -> bytes:
		capsule = self.__compress(args[0], args[1])

		return len(capsule).to_bytes(SIZE_BYTES, byteorder=BYTE_ORDER) + capsule
	
	def __internal_decompression(self, input: bytes) -> bytes:
		return self.__decompress(input)	

class _SingleThreadedAESCipher(object):
	__IV_SIZE = 12
	__MODE = AES.MODE_GCM
	__AES_NI = True
	
	"""
	This class must not be used outside of the Plasma library.
	"""
	def __init__(self, key: bytes):
		self.key = self.__hash_iterations(key)

	def encrypt(self, raw: bytes) -> bytes:
		iv = Random.new().read(self.__IV_SIZE)
		cipher = AES.new(self.key, self.__MODE, iv, use_aesni=self.__AES_NI)
		return iv + cipher.encrypt(raw)

	def decrypt(self, enc: bytes) -> bytes:
		iv = enc[:self.__IV_SIZE]
		cipher = AES.new(self.key, self.__MODE, iv, use_aesni=self.__AES_NI)
		return cipher.decrypt(enc[self.__IV_SIZE:])
		
	@staticmethod
	def __hash_iterations(b: bytes, i: int = 0xFFFF):
		for _ in range(i):
			b = hashlib.sha256(b).digest()
		return b

class ParallelAESInterface(_SingleThreadedAESCipher):
	"""
	Non-threadsafe class that automatically spawns processes for continued use.
	"""
	def __init__(self, key: bytes, nodes: int = cpu_count()):
		"""
		Args:
			nodes: integer, amount of processes to spawn. Usually, you should use the default value.
		"""
		super().__init__(key)
		
		self.__pool = ThreadPool(nodes)
		self.__internal_node_count = nodes
		
	def __encapsulated_encryption(self, raw: bytes) -> bytes:
		capsule = super().encrypt(raw)
		
		return len(capsule).to_bytes(SIZE_BYTES, byteorder=BYTE_ORDER) + capsule
		
	def encrypt(self, raw: bytes) -> bytes:
		"""
		Main encryption function.
		Args:
			raw: Bytes to encrypt
		"""
		chunks = list(self.__chunks(raw, (lambda x: x if x != 0 else 1)(int(round(len(raw) / self.__internal_node_count)))))
		chunks = self.__pool.map(self.__encapsulated_encryption, chunks)
		return b''.join(chunks)
		
	def decrypt(self, enc: bytes) -> bytes:
		"""
		Main decryption function.
		Args:
			enc: Bytes to decrypt
		"""
		chunks = []
		while len(enc) > 0:
			chunk_length = int.from_bytes(enc[:SIZE_BYTES], byteorder=BYTE_ORDER)
			chunks.append(enc[SIZE_BYTES:SIZE_BYTES+chunk_length])
			enc = enc[SIZE_BYTES+chunk_length:]

		return b''.join(self.__pool.map(super().decrypt, chunks))
	
	@staticmethod
	def __chunks(l, n):
		for i in range(0, len(l), n):
			yield l[i:i+n]

if __name__ == '__main__':
	import os, random
	data = os.urandom(1024*1024*16)
	x = ParallelCompressionInterface()
	a = x.compress(data)
	b = x.decompress(a)
	assert b == data

	x = _SingleThreadedAESCipher(os.urandom(8192))
	st = time.time()
	a = x.encrypt(data)
	print((time.time() - st) * 1000)
	st = time.time()
	b = x.decrypt(a)
	print((time.time() - st) * 1000)
	assert b == data
	
	x = ParallelAESInterface(os.urandom(8192))
	st = time.time()
	a = x.encrypt(data)
	print((time.time() - st) * 1000)
	print((len(data) * (1 / (time.time() - st))) / 1024 / 1024)
	st = time.time()
	b = x.decrypt(a)
	print((time.time() - st) * 1000)
	assert b == data
	print(len(a) - len(data))
