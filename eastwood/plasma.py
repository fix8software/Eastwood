"""
Naphtha's craaazy parallel compression class for high speed tasks such as mass network transmission
"""
from psutil import cpu_count
from multiprocessing.pool import ThreadPool

# Import different algorithms for various stages of compression
import zstd as algo # Used for all blocks

# These variables are the ones that probably won't break anything if you change them.
# Please note that these values must be the same for both the compressor and decompressor.
SIZE_BYTES = 4
BYTE_ORDER = 'little'

class ParallelCompressionInterface(object):
	"""
	Non-threadsafe class that automatically spawns processes for continued use.
	"""
	def __init__(self, nodes: int = cpu_count() * 2):
		"""
		Args:
			nodes: integer, amount of processes to spawn. Usually, you should use the default value.
		"""

		self.__pool = ThreadPool(nodes)
		self.__internal_node_count = nodes

	def __level_arguments(self, chunk: bytes, level: int) -> tuple:
		"""
		Private function to automatically prepare arguments for internal compression and starmapping.
		"""
		return (chunk, level)

	def __chunks(self, l, n):
		"""
		Quickest way to break up compression data into multiple chunks of bytes.
		"""
		for i in range(0, len(l), n):
			yield l[i:i+n]

	def compress(self, input: bytes, level: int = 9, chunks: int = -1) -> bytes:
		"""
		Main compression function.
		Args:
			input: Bytes to compress
			level: Compression level
			chunks: Chunks to compress with
		"""

		if chunks < 1:
			chunks = self.__internal_node_count

		chunks = list(self.__chunks(input, (lambda x: x if x != 0 else 1)(int(round(len(input) / chunks)))))
		chunks = self.__pool.imap(_internal_compression, [self.__level_arguments(c, level) for c in chunks])

		return b''.join(chunks)

	def decompress(self, input: bytes) -> bytes:
		"""
		Main decompression function.
		Args:
			input: Bytes to decompress - Note this is not compatible with the output of the standard compression function.
		"""

		chunks = []
		while len(input) > 0:
			chunk_length = int.from_bytes(input[:SIZE_BYTES], byteorder=BYTE_ORDER)
			chunks.append(input[SIZE_BYTES:SIZE_BYTES+chunk_length])
			input = input[SIZE_BYTES+chunk_length:]

		return b''.join(self.__pool.imap(_internal_decompression, chunks))

def _compress(input: bytes, level: int = 6) -> bytes:
	return algo.compress(input, level)

def _decompress(input: bytes) -> bytes:
	return algo.decompress(input)

def _internal_compression(args) -> bytes:
	capsule = _compress(args[0], args[1])

	return len(capsule).to_bytes(SIZE_BYTES, byteorder=BYTE_ORDER) + capsule

def _internal_decompression(input: bytes) -> bytes:
	return _decompress(input)
