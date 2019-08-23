"""
Naphtha's craaazy parallel compression class for high speed tasks such as mass network transmission
"""
from psutil import cpu_count
from multiprocessing.pool import ThreadPool

# Import different algorithms for various stages of compression
import bz2 as algo # Used for all blocks
import lzma as backup # Used for blocks with dangerous sizes
import zstd as single # Used for finalizing output

# These variables are the ones that probably won't break anything if you change them.
# Please note that these values must be the same for both the compressor and decompressor.
SIZE_BYTES = 3
BITFLAG_BYTES = 1
BACKUP_ENABLED = True # Specifies if LZMA should be used when Bzip2 fails
BACKUP_PRESET = 0 # Probably want to keep this at zero for performance reasons

# These are pretty important in general and you shouldn't touch them at all.
BACKUP_FILTERS = [
    {"id": backup.FILTER_LZMA1, "preset": BACKUP_PRESET}
]
BYTE_ORDER = 'little'
FINALIZED_BITFLAGS = {
    True: int(0b00000001).to_bytes(BITFLAG_BYTES, byteorder=BYTE_ORDER),
    False: int(0b00000000).to_bytes(BITFLAG_BYTES, byteorder=BYTE_ORDER)
}

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

    def compress(self, input: bytes, level: int = 6, chunks: int = -1, finalize: bool = True, finalize_preset: int = 4, finalize_threshold: int = 2048) -> bytes:
        """
        Main compression function.
        Args:
            input: Bytes to compress
            level: Compression level
            chunks: Chunks to compress with
        """
        if chunks < 1:
            chunks = self.__internal_node_count * 2

        chunks = list(self.__chunks(input, (lambda x: x if x != 0 else 1)(int(round(len(input) / chunks)))))
        chunks = self.__pool.map(_internal_compression, [self.__level_arguments(c, level) for c in chunks])

        raw = b''.join(chunks)

        if finalize == True and len(raw) >= finalize_threshold:
            finalized = single.compress(raw, finalize_preset)
            if len(finalized) >= len(raw):
                return FINALIZED_BITFLAGS[False] + raw

            return FINALIZED_BITFLAGS[True] + finalized
        else:
            return FINALIZED_BITFLAGS[False] + raw

    def decompress(self, input: bytes) -> bytes:
        """
        Main decompression function.
        Args:
            input: Bytes to decompress - Note this is not compatible with the output of the standard compression function.
        """
        if input[:BITFLAG_BYTES] == FINALIZED_BITFLAGS[True]:
            input = single.decompress(input[BITFLAG_BYTES:])
        else:
            input = input[BITFLAG_BYTES:]

        chunks = []
        while len(input) > 0:
            chunk_length = int.from_bytes(input[:SIZE_BYTES], byteorder=BYTE_ORDER)
            chunks.append(input[SIZE_BYTES:SIZE_BYTES+chunk_length])
            input = input[SIZE_BYTES+chunk_length:]

        return b''.join(self.__pool.map(_internal_decompression, chunks))

def _compress(input: bytes, level: int = 6) -> bytes:
    return algo.compress(input, level)

def _decompress(input: bytes) -> bytes:
    return algo.decompress(input)

def _internal_compression(args) -> bytes:
    capsule = _compress(args[0], args[1])

    info_bitflag = 0b00000000

    if  len(capsule) < len(args[0]):
        info_bitflag = 0b00000001
    elif BACKUP_ENABLED == True:
        capsule = backup.compress(args[0], format=backup.FORMAT_RAW, filters=BACKUP_FILTERS)
        if   len(capsule) < len(args[0]):
            info_bitflag = 0b00000010
        else:
            capsule = args[0]
    else:
        capsule = args[0]

    return (len(capsule)+1).to_bytes(SIZE_BYTES, byteorder=BYTE_ORDER) + capsule + int(info_bitflag).to_bytes(BITFLAG_BYTES, byteorder=BYTE_ORDER)

def _internal_decompression(input: bytes) -> bytes:
    BITFLAG = int.from_bytes(input[-BITFLAG_BYTES:], byteorder=BYTE_ORDER)
    if   BITFLAG == 0b00000001:
        finished = _decompress(input[:-BITFLAG_BYTES])
    elif BITFLAG == 0b00000010:
        finished = backup.decompress(input, format=backup.FORMAT_RAW, filters=BACKUP_FILTERS)
    elif BITFLAG == 0b00000000:
        finished = input[:-BITFLAG_BYTES]

    return finished
