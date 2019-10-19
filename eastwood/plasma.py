"""
P L A S M A

Naphtha's library for parallel, timed operations such as Compression
and Encryption.
"""
from Crypto import Random
from Crypto.Cipher import AES
from psutil import cpu_count
from multiprocessing.pool import ThreadPool
from multiprocessing import Pool
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from threading import Thread
from secrets import token_bytes
from collections import deque
import zstandard as zstd
import zlib, time, os, hashlib, random, math, copy, bz2, functools, sys

# These are the only classes that ought to be used with Plasma publicly.
__all__ = ["ParallelAESInterface", "ParallelCompressionInterface", "IteratedSaltedHash"]

# These variables are the ones that probably won't break anything if you change them.
# Please note that these values must be the same for both the compressor and decompressor.
SIZE_BYTES = 3
META_BYTES = 1
BYTE_ORDER = 'little'

try:
	DEBUG = (lambda x: True if x == 'DEBUG' else False)(sys.argv[1])
except IndexError:
	DEBUG = False

class ThreadMappedObject(object):
	__POOL_TYPE = 'multiprocessing'
	__THREAD_COUNT = cpu_count() * 2

	def __init__(self):
		super().__init__()

	def __new__(cls, *args, **kwargs):
		if cls.__POOL_TYPE == 'concurrent.futures':
			cls.__GLOBAL_POOL = ThreadPoolExecutor(max_workers = cls.__THREAD_COUNT)
			cls.Σ = cls.__GLOBAL_POOL.map
		elif cls.__POOL_TYPE == 'multiprocessing':
			cls.__GLOBAL_POOL = ThreadPool(cls.__THREAD_COUNT)
			cls.Σ = cls.__GLOBAL_POOL.imap
		cls.θ = cls.__THREAD_COUNT
		
		return object.__new__(cls)

class _BZip2ParallelCompressionInterface(ThreadMappedObject):
	# bzip2 attributes
	__MAX_LEVEL = 9
	__MIN_LEVEL = 1
	
	def __init__(self, nodes: int = cpu_count(), target_speed_ms: int = 60, target_speed_buf: int = 5):
		self.nodes = nodes
		self.__target_speed = target_speed_ms
		self.__target_buf = target_speed_buf
		self.__average_time = deque([0], maxlen=255)
		self.__table = {}
		
		self.last_level = self.__MAX_LEVEL
		self.__global_level = self.__MAX_LEVEL
		
		self.create_level_table()

	def create_level_table(self, size = 262144):
		self.__table = {}
		self.__table_size = size
		
		crand = ThreadedModPseudoRandRestrictedRand()
		data = [
			token_bytes(self.__table_size),
			os.urandom(self.__table_size),
			crand.random(self.__table_size),
			os.urandom(1) + b'\x00' * self.__table_size
		]
		
		for x in data:
			# This, for some reason, helps get a better result on
			# the first level during the real task. ¯\_(ツ)_/¯
			__ = self.compress(x, self.__MIN_LEVEL)
		
		for level in range(self.__MIN_LEVEL, self.__MAX_LEVEL + 1):
			times = []
			for x in data:
				for _ in range(2):
					s = time.time()
					__ = self.compress(x, level)
					t = time.time() - s
					times.append(t)
			a = sum(times) / len(times)
			timebyte = (a / self.__table_size)
		
			self.__table[level] = (timebyte)
			
		return self.__table
		
	@functools.lru_cache(maxsize=4)
	def compress(self, input: bytes, level: int = -1):
		if level < self.__MIN_LEVEL:
			accept_level = self.__MIN_LEVEL
			for k, v in self.__table.items():
				if ((v * len(input)) * 1000) < self.__target_speed + self.__target_buf:
					accept_level = k
		
			flevel = int(round((self.__global_level + accept_level) / 2))
		else:
			flevel = level
	
		startt = time.time()
		result = self.__p_compress(input, flevel)
		
		if level < self.__MIN_LEVEL:
			msec = ((time.time() - startt) * 1000)
			
			if DEBUG:
				print('[DEBUG] Compression Time: {0}ms'.format(msec))
			
			self.__average_time.append(((sum(self.__average_time) / len(self.__average_time)) + msec) / 2)

			averaged = self.__average_time[-1]
			
			if averaged > self.__target_speed and self.__global_level > self.__MIN_LEVEL:
				self.__global_level -= 1
			elif averaged < self.__target_speed - self.__target_buf and self.__global_level < self.__MAX_LEVEL:
				self.__global_level += 1
		
		self.last_level = flevel
		
		if len(result) > len(input):
			meta = self.__int_in(0b00000000)
			result = input
		else:
			meta = self.__int_in(0b00000001)
			
		return meta + result
		
	def __p_compress(self, input: bytes, level: int) -> bytes:
		x = self.__chunks(input, 98304 * level)
		
		self.cu_lev = level
		return b''.join(self.Σ(self.__encapsulated_compression, list(x)))
		
	def __encapsulated_compression(self, raw: bytes) -> bytes:
		capsule = bz2.compress(raw, self.cu_lev)

		return len(capsule).to_bytes(SIZE_BYTES, byteorder=BYTE_ORDER) + capsule
		
	@functools.lru_cache(maxsize=4)
	def decompress(self, input: bytes) -> bytes:
		"""
		Main decompression function.
		Args:
			input: Bytes to decompress - Note this is not compatible with the output of the standard compression function.
		"""

		startt = time.time()
		if self.__int_out(input[:META_BYTES]) == 0b00000000:
			return input[META_BYTES:]
		else:
			input = input[META_BYTES:]

		chunks = []
		while len(input) > 0:
			chunk_length = int.from_bytes(input[:SIZE_BYTES], byteorder=BYTE_ORDER)
			chunks.append(input[SIZE_BYTES:SIZE_BYTES+chunk_length])
			input = input[SIZE_BYTES+chunk_length:]
			
		result = b''.join(self.Σ(bz2.decompress, chunks))
		msec = ((time.time() - startt) * 1000)
		
		if DEBUG:
			print('[DEBUG] Decompression Time: {0}ms'.format(msec))
				
		return result
		
	@staticmethod
	def __chunks(l, n):
		for i in range(0, len(l), n):
			yield l[i:i+n]
			
	@staticmethod
	def __int_in(i: int, s: int = META_BYTES):
		return i.to_bytes(s, byteorder=BYTE_ORDER)

	@staticmethod
	def __int_out(i: bytes):
		return int.from_bytes(i, byteorder=BYTE_ORDER)

class _ZStandardParallelCompressionInterface(object):
	# zstd attributes
	__MAX_LEVEL = 22
	__MIN_LEVEL = 1
	
	def __init__(self, nodes: int = cpu_count(), target_speed_ms: int = 50, target_speed_buf: int = 10):
		self.nodes = nodes
		self.__target_speed = target_speed_ms
		self.__target_buf = target_speed_buf
		self.__average_time = deque([0], maxlen=8192)
		self.__table = {}
		
		self.last_level = self.__MAX_LEVEL
		self.__global_level = self.__MAX_LEVEL
		
		self.__create_zstandard_D()
		
		self.create_level_table()
		
	def create_level_table(self, size = 16384):
		self.__table = {}
		self.__table_size = size
		
		crand = ThreadedModPseudoRandRestrictedRand()
		data = [
			token_bytes(self.__table_size),
			os.urandom(self.__table_size),
			crand.random(self.__table_size),
			b'\x00' * self.__table_size
		]
		
		for x in data:
			# This, for some reason, helps get a better result on
			# the first level during the real task. ¯\_(ツ)_/¯
			__ = self.compress(x, self.__MIN_LEVEL)
		
		for level in range(self.__MIN_LEVEL, self.__MAX_LEVEL + 1):
			times = []
			for x in data:
				for _ in range(2):
					s = time.time()
					__ = self.compress(x, level)
					t = time.time() - s
					times.append(t)
			a = sum(times) / len(times)
			timebyte = (a / self.__table_size)
		
			self.__table[level] = (timebyte)
			
		return self.__table
		
	def __create_zstandard_D(self):
		self.decompressionObject = zstd.ZstdDecompressor()
		
	def compress(self, input: bytes, level: int = -1):
		if level < self.__MIN_LEVEL:
			accept_level = self.__MIN_LEVEL
			for k, v in self.__table.items():
				if ((v * len(input)) * 1000) < self.__target_speed + self.__target_buf:
					accept_level = k
		
			flevel = int(round((self.__global_level + accept_level) / 2))
		else:
			flevel = level
	
		startt = time.time()
		x = zstd.ZstdCompressor(level = flevel, threads = self.nodes)
		y = x.compress(input)
		
		if level < self.__MIN_LEVEL:
			msec = ((time.time() - startt) * 1000)
			self.__average_time.append(((sum(self.__average_time) / len(self.__average_time)) + msec) / 2)

			averaged = self.__average_time[-1]
			
			if averaged > self.__target_speed and self.__global_level > self.__MIN_LEVEL:
				self.__global_level -= 1
			elif averaged < self.__target_speed - self.__target_buf and self.__global_level < self.__MAX_LEVEL:
				self.__global_level += 1
		
		self.last_level = flevel
		return y
		
	def decompress(self, input: bytes) -> bytes:
		return self.decompressionObject.decompress(input)

class ParallelCompressionInterface(ThreadMappedObject):
	# zstd attributes
	__MAX_LEVEL = 22
	__MIN_LEVEL = 1
	__TOO_LOW_MAX = 8
	__UNLEARN_INTERVAL_SECONDS = 60
	__ATHS_START = 0x003FFFFF

	"""
	Non-threadsafe class that automatically spawns processes for continued use.
	"""
	def __init__(self, nodes: int = cpu_count(), target_speed_ms: int = 150):
		"""
		Args:
			nodes: integer, amount of processes to spawn. Usually, you should use the default value.
		"""

		self.__big_data = b''
		self.__global_level = self.__MAX_LEVEL
		self.__average_time = 0
		self.__target_speed = target_speed_ms
		self.__average_too_high_size = self.__ATHS_START
		self.__unlearn_setback = self.__jitter_setback_training()
		self.__average_too_high_size = self.__unlearn_setback
		self.__global_level = self.__MAX_LEVEL

		self.__threads = []

		self.__threads.append(Thread(target=self.__jitter_training_reinitialization_thread))
		self.__threads[-1].daemon = True
		self.__threads[-1].start()

		self.last_level = self.__global_level

	def __jitter_setback_training(self) -> int:
		increment = (2 ** 18) - 1
		speed = 0
		size = increment
		# level = int(round((self.__MAX_LEVEL + self.__MIN_LEVEL) / 2))
		level = self.__MAX_LEVEL
		while speed < self.__target_speed:
			data = token_bytes(size)
			# tt = []
			# for _ in range(2):
			# 	st = time.time()
			# 	__ = self.compress(data, level)
			# 	tt.append((time.time() - st) * 1000)
			# speed = sum(tt) / len(tt)
			st = time.time()
			__ = self.compress(data, level)
			speed = (time.time() - st) * 1000
			size += increment
		return size * 4

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
			level = int(round((self.__global_level + suggested) / 2))

		startt = time.time()
		chunks = list(self.__chunks(input, (lambda x: x if x != 0 else 1)(int(round(len(input) / self.θ)))))
		chunks = self.Σ(self.__internal_compression, [self.__level_arguments(c, level) for c in chunks])
		result = b''.join(chunks)

		msec = ((time.time() - startt) * 1000)
		self.__average_time = (self.__average_time + msec) / 2
		if self.__average_time > self.__target_speed and self.__global_level > self.__MIN_LEVEL:
			self.__global_level -= 1
		elif self.__average_time < self.__target_speed and self.__global_level < self.__MAX_LEVEL:
			self.__global_level += 1

		if self.__average_time > self.__target_speed:
			self.__average_too_high_size = int(round((self.__average_too_high_size + len(input)) / 2))
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

		return b''.join(self.Σ(self.__internal_decompression, chunks))

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

ParallelCompressionInterface = _BZip2ParallelCompressionInterface

class _SingleThreadedAESCipher(ThreadMappedObject):
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
	def __encapsulated_encryption(self, raw: bytes) -> bytes:
		capsule = super().encrypt(raw)

		return len(capsule).to_bytes(SIZE_BYTES, byteorder=BYTE_ORDER) + capsule

	def encrypt(self, raw: bytes) -> bytes:
		"""
		Main encryption function.
		Args:
			raw: Bytes to encrypt
		"""
		chunks = list(self.__chunks(raw, (lambda x: x if x != 0 else 1)(int(round(len(raw) / self.θ)))))
		chunks = self.Σ(self.__encapsulated_encryption, chunks)
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

		return b''.join(self.Σ(super().decrypt, chunks))

	@staticmethod
	def __chunks(l, n):
		for i in range(0, len(l), n):
			yield l[i:i+n]

def IteratedSaltedHash(raw: bytes, salt = None, iterations: int = 0x0002FFFF, salt_length: int = 0xFF, salt_generator = token_bytes) -> tuple:
	"""
	Sauced, salted hash function.
	Args:
		raw: bytes to hash
		salt: bytes or None
	Returns:
		tuple: (bytes, bytes) - The hash, then the salt.
	"""
	salt = (lambda x: x if salt == None else salt)(salt_generator(salt_length))
	for _ in range(iterations):
		raw = hashlib.sha512(raw + salt).digest()
	return (raw, salt)

class ModPseudoRand(ThreadMappedObject):
	def __init__(self):
		self.seed(os.urandom(16))

	def seed(self, raw: bytes):
		self.seedval = zlib.crc32(raw) & 0xffffffff
		self.randobj = random.Random(self.seedval)

	def byte(self):		
		self.seed_progression()
		return self.randobj.randint(0, 255)

	def seed_progression(self):
		pass

	def byte_bytes(self):
		return bytes(self.byte())

	def random(self, size: int = 1):
		return bytes([self.byte() for _ in range(size)])

class ModPseudoRandRestrictedSeed(ModPseudoRand):
	def __init__(self):
		super().__init__()
		self.__b = ModPseudoRand()
		self.__so = random.Random()

	def seed_progression(self):
		if self.__so.randint(0, 1) == 1:
			self.seed(self.__b.byte_bytes())

class ModPseudoRandRestrictedRand(ModPseudoRand):
	def generator(self):
		return super().random()
	
	def random(self, size: int = 1):
		x = bytes()
		while len(x) < size:
			x += self.generator() * (lambda x, l, u: l if x < l else u if x > u else x)(self.generator()[0], 1, 128)
			
		return x[:size]
	
class CryptoModPseudoRandRestrictedRand(ModPseudoRandRestrictedRand):
	def generator(self):
		return token_bytes(1)
		
class ThreadedModPseudoRandRestrictedRand(ModPseudoRandRestrictedRand):
	def random(self, size: int = 1):
		return b''.join(self.Σ(super().random, [math.ceil(size / self.θ) for _ in range(self.θ)]))[:size]
	
if __name__ == '__main__':
	# THIS IS THE BADLY WRITTEN SCRIPT USED FOR TESTING PLASMA.
	# DON'T RUN THIS.
	
	import cProfile, sys
	x = ThreadedModPseudoRandRestrictedRand()
	
	st = time.time()
	n = x.random(512 * 1024)
	print((time.time() - st) * 1000)
	
	data = os.urandom(512 * 1024)
	st = time.time()
	x = ParallelCompressionInterface()
	print((time.time() - st) * 1000)
	for _ in range(8):
		st = time.time()
		a = x.compress(data)
		print(str((time.time() - st) * 1000) + ' - ' + str(x.last_level))
	b = x.decompress(a)
	assert b == data
	
	data = n
	st = time.time()
	x = ParallelCompressionInterface()
	print((time.time() - st) * 1000)
	for _ in range(8):
		st = time.time()
		a = x.compress(data)
		print(str((time.time() - st) * 1000) + ' - ' + str(x.last_level) + ' - ' + str(len(a)))
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

	x, y = IteratedSaltedHash(b'helloworld')
	print(x)