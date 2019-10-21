"""
P L A S M A

Naphtha's library for parallel, timed operations such as Compression
and Encryption.

Exposes the following utilities:
    - ParallelAESInterface - Fast AES encryption
    - ParallelCompressionInterface - Fast AND efficient compression
    - IteratedSaltedHash - Secure password hashing (You ought to use bcrypt though)
    - Khaki - Lightweight data format
    - StaticKhaki - Simpler interface to Khaki
    
Requirements:
    psutil==5.6.3
    zstandard==0.11.1
    pycryptodome==3.9.0
    mmh3==2.5.1
    multiprocess==0.70.9
    colorama==0.4.1
"""

# All module imports
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
import zlib, time, os, hashlib, random, math, copy, bz2, functools, sys, platform
import urllib.request, mmh3, colorama, struct, re, psutil, uuid, json, socket
from multiprocess import Pool as DillPool

# These are the only classes that ought to be used with Plasma publicly.
__all__ = ["ParallelAESInterface", "ParallelCompressionInterface", "IteratedSaltedHash", "StaticKhaki", "Khaki"]

# These variables are the ones that probably won't break anything if you change them.
# Please note that these values must be the same for both the compressor and decompressor.
# SIZE_BYTES (3)        - How many bytes to represent the size of each ParallelCompressionInterface chunk with?
# META_BYTES (1)        - How many bytes to represent the size of metadata with?
# BYTE_ORDER ('little') - What byte order should be used?
SIZE_BYTES = 3
META_BYTES = 1
BYTE_ORDER = 'little'

# Training data to use with the compressor. Only downloaded once.
# By default, it uses around 8 MiB of Minecraft 1.14.4 packet captures.
TRAINING_DATA_URL = 'https://github.com/smplite/Eastwood/raw/master/eastwood/testdata/large_packet_sample.bin'

# Everything important that you ought not to touch starts here.
# ---------------------------------------------------------------------------------------------------------------

# Check for debug mode.
try:
    DEBUG = (lambda x: True if x == 'DEBUG' else False)(sys.argv[1])
except IndexError:
    # If the argument is not set, debug mode is not set.
    DEBUG = False
    
if DEBUG:
    # If debug mode is enabled, we will need colour. Initialize colorama.
    colorama.init()

@functools.lru_cache(maxsize=32) # Minor speed improvement, as Python's built in hash is faster than crc32.
def cachedStringHash(i: str) -> str:
    return hex(zlib.crc32(i.encode('utf8')))[2:] # Only ever take string, only ever produce string.
                                                 # This is designed to serve a very specific purpose.

@functools.lru_cache(maxsize=16) # Prevents checking filesystem multiple times.
def cachedDownload(url: str) -> bytes:
    if not os.path.exists('./cache'): # Check for a cache directory.
        os.makedirs('./cache')        # Make the cache directory if it doesn't exist already.
        
    cache_file = './cache/{0}.pdc'.format(cachedStringHash(url)) # Determine the file's in-cache name.
        
    if not os.path.isfile(cache_file): # If it isn't in the cache, download it.
        response = urllib.request.urlopen(url) # This works just like a regular file handle, surprisingly.
        data = response.read()
        
        with open(cache_file, 'wb') as cache_output: # Write it to the cache file. It will be read again,
                                                     # hence the LRU cache, to prevent constant writing and
                                                     # reading over and over again.
            cache_output.write(data)
            
    with open(cache_file, 'rb') as cache_input: # And this is where the cache is re-read.
        return cache_input.read()

@functools.lru_cache(maxsize=None) # Prevents various checks being performed multiple times.
def getSystemInfo():
    info                     = {}
    info['platform']         = platform.system()
    info['platform-release'] = platform.release()
    info['platform-version'] = platform.version()
    info['architecture']     = platform.machine()
    info['hostname']         = socket.gethostname()
    info['ip-address']       = socket.gethostbyname(socket.gethostname())
    info['mac-address']      = ':'.join(re.findall('..', '%012x' % uuid.getnode())) # You'd think this would be
                                                                                    # slightly easier...
    info['processor']        = platform.processor()
    info['ram']              = str(round(psutil.virtual_memory().total / (1024.0 ** 3)))+" GB"
    return info

class ThreadMappedObject(object):
    __POOL_TYPE = 'multiprocessing' # Multiprocessing seems fastest here.
    __THREAD_COUNT = cpu_count()    # Use twice as many threads as the core count for, apparently, good perf.

    def __init__(self):
        super().__init__()

    def __new__(cls, *args, **kwargs): # Using __new__ in case __init__ is not called.
        if cls.__POOL_TYPE == 'concurrent.futures':
            cls.__GLOBAL_POOL = ThreadPoolExecutor(max_workers = cls.__THREAD_COUNT)
            cls.Σ = cls.__GLOBAL_POOL.map # Create a function "Σ" so that the child class can map iterables to
                                          # the mutliprocessing pool.
                                          # 
                                          # No, I don't know why I decided to pick that function name.
                                          # Yes, I know it's kind of bad practice.
                                          # No, I don't care.
        elif cls.__POOL_TYPE == 'multiprocessing':
            cls.__GLOBAL_POOL = ThreadPool(cls.__THREAD_COUNT)
            cls.Σ = cls.__GLOBAL_POOL.imap
        cls.θ = cls.__THREAD_COUNT # θ represents the amount of threads spawned.
        
        return object.__new__(cls)

class ProcessMappedObject(object):
    __POOL_TYPE = 'multiprocessing'
    __THREAD_COUNT = cpu_count()

    def __init__(self):
        super().__init__()

    def __new__(cls, *args, **kwargs):
        if cls.__POOL_TYPE == 'concurrent.futures':
            cls.__GLOBAL_POOL = ProcessPoolExecutor(max_workers = cls.__THREAD_COUNT)
            cls.Σ = cls.__GLOBAL_POOL.map
        elif cls.__POOL_TYPE == 'multiprocessing':
            cls.__GLOBAL_POOL = Pool(cls.__THREAD_COUNT)
            cls.Σ = cls.__GLOBAL_POOL.imap
        elif cls.__POOL_TYPE == 'multiprocess': # Multiprocess uses dill instead of cPickle.
            cls.__GLOBAL_POOL = DillPool(cls.__THREAD_COUNT)
            cls.Σ = cls.__GLOBAL_POOL.imap
        cls.θ = cls.__THREAD_COUNT
        
        return object.__new__(cls)
        
def encapsulated_byte_func(fargs: tuple) -> bytes:
    """
        This function is not important, other than it is involved with the encapsulation process
        of compressed data chunks. Don't worry about it.
    """
    capsule = fargs[0](*fargs[1]) # Usually, should perform bz2, zstd or zlib compression with a
                                  # given level and data to compress.

    # Here, the result is "encapsulated" by prepending its length.
    return len(capsule).to_bytes(SIZE_BYTES, byteorder=BYTE_ORDER) + capsule

class ZStandardSimpleInterface(object):
    @staticmethod
    def compress(data: bytes, level: int = 1) -> bytes:
        x = zstd.ZstdCompressor(level = level, threads = cpu_count())
        return x.compress(data)
        
    @staticmethod
    def decompress(data: bytes) -> bytes:
        x = zstd.ZstdDecompressor()
        return x.decompress(data)

# Currently ParallelCompressionInterface - Latest features
class _GlobalParallelCompressionInterface(ProcessMappedObject):
    # algo attributes
    __MAX_LEVEL  = 22
    __MIN_LEVEL  = 1
    
    # cache attributes
    __CACHE_SIZE = 16
    
    class ChecksumFailureException(Exception):
        pass
        
    class CacheMiss(Exception):
        pass
    
    def __init__(
            self,
            nodes: int = cpu_count(),       # Thread count.
            cached: bool = False,           # Whether or not to cache requests.
            bz2chunk: bool = False,         # If true, split by block size. If false, split equally.
            exifdata: bool = False,         # If true, add extra information to compression payloads, e.g for calculating checksums.
            target_speed_ms: int = 20,      # Maximum time it should take to compress anything.
            target_speed_buf: int = 5       # When should PRIZMA start to raise the compression level?
        ):
        
        # Allow arguments to be accessed across the class.
        self.cached = cached
        self.nodes = nodes
        self.bz2chunk = bz2chunk
        self.exifdata = exifdata
        
        self.__target_speed = target_speed_ms
        self.__target_buf = target_speed_buf
        
        # Device fingerprint for exif and WAU cache
        self.fingerprint = mmh3.hash(
            StaticKhaki.dumps(
                list(platform.uname()),
                
                compressed = False,
                min_value_length = 4
            )
        )
        
        # WAU/PRIZMA data
        self.__average_time = deque([0], maxlen=8192)
        self.__table = {}
        
        # Compression engine. Works with bz2 OR zlib.
        self.__engine = ZStandardSimpleInterface
        
        # Request caching. Optional.
        self.__compression_cache = {}
        self.__decompression_cache = {}
        
        # Information for whatever uses this class.
        self.last_level = self.__MAX_LEVEL
        
        # PRIZMA level.
        self.__global_level = self.__MAX_LEVEL
        
        # Create the WAU table.
        self.create_level_table()

    def _save_cache(self, element: str, data):
        if not os.path.exists('./cache'): # Check for a cache directory.
            os.makedirs('./cache')        # Make the cache directory if it doesn't exist already.
            
        cache_file = './cache/{0}.pdc'.format(cachedStringHash(element)) # Determine the file's in-cache name.
            
        with open(cache_file, 'wb') as cache_output: # Write it to the cache file. It will be read again,
                                                     # hence the LRU cache, to prevent constant writing and
                                                     # reading over and over again.
            cache_output.write(StaticKhaki.dumps(data))
            
    def _get_cache(self, element: str):
        if not os.path.exists('./cache'): # Check for a cache directory.
            os.makedirs('./cache')        # Make the cache directory if it doesn't exist already.
            
        cache_file = './cache/{0}.pdc'.format(cachedStringHash(element)) # Determine the file's in-cache name.
            
        if not os.path.isfile(cache_file): # If it isn't in the cache, report it.
            raise self.CacheMiss()
            
        with open(cache_file, 'rb') as cache_input: # And this is where the cache is re-read.
            return StaticKhaki.loads(cache_input.read())

    def create_level_table(self, size = 262144, low_size = 16384, max_size = 1048576):
        """
        This function creates everything a system called WAU needs to improve compression speed.
        
        Based on the data stored in the table this produces, WAU can automatically adjust the
        compression level based on the length of the data provided.
        """
        
        data = [
            # Assuming a table size of 262144, this will perform tests on parts of the training data
            # with a size of 262144 per test. In total, about 1 MiB of the data should be tested.
            cachedDownload(TRAINING_DATA_URL)[      :size  ],
            cachedDownload(TRAINING_DATA_URL)[size  :size*2],
            cachedDownload(TRAINING_DATA_URL)[size*2:size*3],
            cachedDownload(TRAINING_DATA_URL)[size*3:size*4],
            
            # Low size tests to ensure the time per byte value is fair
            cachedDownload(TRAINING_DATA_URL)[          :low_size  ],
            cachedDownload(TRAINING_DATA_URL)[low_size  :low_size*2],
            cachedDownload(TRAINING_DATA_URL)[low_size*2:low_size*3],
            cachedDownload(TRAINING_DATA_URL)[low_size*3:low_size*4],
            
            # A few max size tests
            cachedDownload(TRAINING_DATA_URL)[          :max_size  ],
            cachedDownload(TRAINING_DATA_URL)[max_size  :max_size*2],
            cachedDownload(TRAINING_DATA_URL)[max_size*2:max_size*3],
            cachedDownload(TRAINING_DATA_URL)[max_size*3:max_size*4],
        ]
    
        cache_object_name = '{0} Compression Object Cache (Device: {1}, Fortnight Timestamp: {2}, Training Data: {3})'.format(
            type(self).__name__,           # Cache by compressor type
            self.fingerprint,              # Cache by device type
            round(time.time() / 1209600),  # Update cache every 14 days
            mmh3.hash(                     # Cache by training data
                StaticKhaki.dumps(
                    data,
                    
                    compressed = False,
                    min_value_length = 4
                )
            )
        )
    
        try:
            self.__table = self._get_cache(cache_object_name)
        except self.CacheMiss:
            self.__table = {}
            self.__table_size = size
            
            for x in data:
                # This, for some reason, helps get a better result on
                # the first level during the real task. ¯\_(ツ)_/¯
                __ = self.compress(x, self.__MIN_LEVEL)
            
            # Generate values for each compression level.
            for level in range(self.__MIN_LEVEL, self.__MAX_LEVEL + 1):
                times = []
                for x in data:
                    for _ in range(2): # Perform twice for accuracy.
                        s = time.time()
                        __ = self.compress(x, level)
                        t = time.time() - s
                        times.append(t)
                a = sum(times) / len(times)
                timebyte = (a / self.__table_size) # Calculate the time per byte.
            
                self.__table[level] = (timebyte)
                
            self._save_cache(cache_object_name, self.__table)
        else:
            pass
                
        return self.__table
        
    def compress(self, input: bytes, level: int = -1):
        """
        Main compression function.
        Args:
            input: Bytes to compress
            level: Compression level (Set to -1 for WAU/PRIZMA auto-set)
        """
        if self.cached:
            # Check if the compressed data is already in the cache.
            v_key = mmh3.hash128(input + self.__int_in(level & 0xff))
        
            if v_key in self.__compression_cache.keys():
                return self.__compression_cache[v_key] # Return it if it is.
    
        startt = time.time() # Begin timing compression for PRIZMA.
    
        # If the level is invalid, switch to auto.
        if level < self.__MIN_LEVEL:
            accept_level = self.__MIN_LEVEL
            for k, v in self.__table.items(): # WAU (length level system)
                                              # Move along table until appropriate level found.
                if ((v * len(input)) * 1000) < self.__target_speed + self.__target_buf:
                    accept_level = k
        
            flevel = int(round((self.__global_level + accept_level) / 2)) # PRIZMA (global level system)
        else:
            flevel = level
    
        result = self.__p_compress(input, flevel) # Perform parallel compression here.
        
        msec = -1 # In case auto-level is off, set time to -1 for exif data.
        if level < self.__MIN_LEVEL:
            msec = ((time.time() - startt) * 1000)
            
            # Print debug information if enabled.
            if DEBUG:
                print(
                    '[DEBUG] '+colorama.Fore.RED+colorama.Style.BRIGHT+'Compression'+colorama.Style.RESET_ALL+' Time: {0}ms at level {1} ({2} times smaller)'.format(
                        str(round(msec, 1)).ljust(10),
                        str(flevel).ljust(4),
                        str(int(round(len(input) / len(result)))).ljust(8)
                    )
                )
            
            # Perform PRIZMA calculations, where global level is lowered if compression took too long and
            # global level is raised if it didn't take enough time.
            self.__average_time.append(((sum(self.__average_time) / len(self.__average_time)) + msec) / 2)

            averaged = self.__average_time[-1]
            
            if averaged > self.__target_speed and self.__global_level > self.__MIN_LEVEL:
                self.__global_level -= 1
            elif averaged < self.__target_speed - self.__target_buf and self.__global_level < self.__MAX_LEVEL:
                self.__global_level += 1
        
        # Expose the last level selected to exterior processes.
        self.last_level = flevel
            
        # Generate EXIF/ExIf (Extra Information), which can be used by the decompressor for debug or verification purposes.
        
        if self.exifdata:
            exif = {
                'compression_time'   : msec,
                'compressed_at'      : startt,
                'original_size'      : len(input),
                'compressed_size'    : len(result),
                'compression_level'  : flevel,
                'specified_level'    : level,
                'checksum'           : mmh3.hash(input),
                'compressed_checksum': mmh3.hash(result),
                'platform'           : getSystemInfo(),
                'device_fingerprint' : self.fingerprint,
                'caching_enabled'    : self.cached
            }
        else:
            exif = None
        
        final = StaticKhaki.dumps({
            'compressed': result,
            
            'exif': exif
        }, compressed = False, min_value_length = 4)
        
        # If caching is enabled, cache this data.
        if self.cached:
            if len(self.__compression_cache) >= self.__CACHE_SIZE:
                # Delete an entry from the cache if there are too many of them.
                del self.__compression_cache[list(self.__compression_cache.keys())[0]]
            self.__compression_cache[v_key] = final
            
        return final
        
    def __p_compress(self, input: bytes, level: int) -> bytes:
        # This is where parallel compression is finally performed.
        # First, break up the data into chunks roughly the size of the compression engine's block size at each level.
        if self.bz2chunk:
            x = self.__chunks(input, 32768 * level)
        else:
            x = self.__chunks(input, int(round(len(input) / self.nodes)))
        
        # Then, create encapsulation arguments containing level, data and compression engine.
        # Then call the encapsulation function in the process pool.
        # Then join up the output to form a continuous string of bytes.
        return b''.join(
            self.Σ(
                encapsulated_byte_func,
                [
                    (
                        self.__engine.compress,
                        self.__level_arguments(c, level)
                    ) for c in x
                ]
            )
        )
        
    def decompress(self, input: bytes) -> bytes:
        """
        Main decompression function.
        Args:
            input: Bytes to decompress - Note this is not compatible with the output of the standard compression function.
        """
        
        # Calculate the input length before the variable is modified.
        input_length = len(input)
        
        # Same caching situation as before in compress()
        if self.cached:
            v_key = mmh3.hash128(input)
        
            if v_key in self.__decompression_cache.keys():
                return self.__decompression_cache[v_key]

        # This time, timing is only required for debugging purposes.
        startt = time.time()
        
        # Feed the compressor's output through Khaki to decode it.
        decoded = StaticKhaki.loads(input)
        
        # This is all we need to actually perform the decompression.
        input = decoded['compressed']

        # Break it all back up into chunks for parallel decompression.
        chunks = []
        while len(input) > 0: # Remove from input until it is empty.
            chunk_length = int.from_bytes(input[:SIZE_BYTES], byteorder=BYTE_ORDER)
            chunks.append(input[SIZE_BYTES:SIZE_BYTES+chunk_length])
            input = input[SIZE_BYTES+chunk_length:]
            
        # Parallel decompression is much easier than parallel compression, as we don't need to specify a level.
        result = b''.join(self.Σ(self.__engine.decompress, chunks))
        msec = ((time.time() - startt) * 1000) # The final time it took to decompress.
        
        # Again, more debug printing.
        if DEBUG and decoded['exif'] is not None:
            print(
                '[DEBUG] '+colorama.Fore.GREEN+colorama.Style.BRIGHT+'Decompress.'+colorama.Style.RESET_ALL+' Time: {0}ms at level {1} ({2} times bigger )'.format(
                    str(round(msec, 1)).ljust(10),
                    str(decoded['exif']['compression_level']).ljust(4),
                    str(int(round(len(result) / input_length))).ljust(8)
                )
            )
                
        # Same caching situation as before.
        if self.cached:
            if len(self.__decompression_cache) >= self.__CACHE_SIZE:
                del self.__decompression_cache[list(self.__decompression_cache.keys())[0]]
            self.__decompression_cache[v_key] = result
                
        # Use compression exif to determine if output is valid.
        if decoded['exif'] is not None:
            if decoded['exif']['checksum'] != mmh3.hash(result):
                raise self.ChecksumFailureException('The decompressor has yielded invalid data! Check the integrity of your data stream.')
                
        return result
        
    @staticmethod
    def __chunks(l, n):
        """
        This static method is used to break up data into chunks of n size.
        """
        for i in range(0, len(l), n):
            yield l[i:i+n]
            
    @staticmethod
    def __int_in(i: int, s: int = META_BYTES):
        """
        Convert integer i into s bytes.
        """
        return i.to_bytes(s, byteorder=BYTE_ORDER)

    @staticmethod
    def __int_out(i: bytes):
        """
        Convert i (bytes) into integer.
        """
        return int.from_bytes(i, byteorder=BYTE_ORDER)
        
    @staticmethod
    def __level_arguments(chunk: bytes, level: int) -> tuple:
        """
        Private function to automatically prepare arguments for internal compression.
        """
        return (chunk, level)

# OBSOLETED: Too slow.
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

# OBSOLETED: Segfaulted, somehow
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
            #   st = time.time()
            #   __ = self.compress(data, level)
            #   tt.append((time.time() - st) * 1000)
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
            suggested = (lambda x,l,u: l if x<l else u if x>u else x)( # Check if within range
                (lambda x,a,b,c,d: (x-a)/(b-a)*(d-c)+c)(               # Map to range
                    len(input),                                        # Input Length
                    0,                                                 # Min. Input Length
                    self.__average_too_high_size,                      # Max. Level Size
                    self.__MAX_LEVEL,                                  # Max. Level
                    self.__MIN_LEVEL                                   # Min. Level
                ),
                self.__MIN_LEVEL,                                      # Wrap map result to min/max lvl
                self.__MAX_LEVEL
            )
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

ParallelCompressionInterface = _GlobalParallelCompressionInterface

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
    
class Khaki(object):
    """
    Universal lightweight format for encoding and decoding primitive data
    """

    def dumps(self, i, compressed = True, min_value_length: int = 1) -> bytes:
        """
        Turn any primitive data type into an array of bytes
        """
    
        if compressed:
            return struct.pack('<?', True ) + zlib.compress(self.to_bytes(i, min_value_length), level = 1)
        else:
            return struct.pack('<?', False) +               self.to_bytes(i, min_value_length)
        
    def loads(self, i: bytes):
        """
        Reverse of Khaki.dumps()
        
        Turns bytes into Python data types
        """
    
        compressed = struct.unpack('<?', i[:1])[0]
    
        if compressed:
            return self.from_bytes(zlib.decompress(i[1:]))
        else:
            return self.from_bytes(i[1:])

    class KhakiUnknownTypeException(Exception):
        pass
        
    class KhakiUtility(object):
        META = 1
    
        @staticmethod
        def intToBytes(i: int, s: int = META):
            return i.to_bytes(s, byteorder=BYTE_ORDER, signed = True)

        @staticmethod
        def bytesToInt(i: bytes):
            return int.from_bytes(i, byteorder=BYTE_ORDER, signed = True)

    def to_bytes(self, i, starting_vlen: int = 1) -> bytes:
        ready = False
        
        vlen = starting_vlen
        while ready == False:
            try:
                output = bytes()
                output += self.KhakiUtility.intToBytes(vlen)
            
                if   type(i) == dict:
                    output += self.KhakiUtility.intToBytes(0b00000000)
                
                    for k, v in i.items():
                        key = self.to_bytes(k, starting_vlen)
                        output += self.KhakiUtility.intToBytes(len(key), vlen) + key
                        value = self.to_bytes(v, starting_vlen)
                        output += self.KhakiUtility.intToBytes(len(value), vlen) + value
                elif type(i) == list:
                    output += self.KhakiUtility.intToBytes(0b00000001)
                
                    for x in i:
                        value = self.to_bytes(x, starting_vlen)
                        output += self.KhakiUtility.intToBytes(len(value), vlen) + value
                elif type(i) == str:
                    output += self.KhakiUtility.intToBytes(0b00000010) + i.encode('utf8')
                elif type(i) == int:
                    try:
                        output += self.KhakiUtility.intToBytes(0b00000011) + struct.pack('<q', i)
                    except struct.error:
                        try:
                            output += self.KhakiUtility.intToBytes(0b00001000) + self.KhakiUtility.intToBytes(i, 32)
                        except OverflowError:
                            output += self.KhakiUtility.intToBytes(0b00001001) + self.to_bytes(str(i), starting_vlen)
                elif type(i) == float:
                    output += self.KhakiUtility.intToBytes(0b00000100) + struct.pack('<d', i)
                elif type(i) == bool:
                    output += self.KhakiUtility.intToBytes(0b00000101) + struct.pack('<?', i)
                elif type(i) == bytes:
                    output += self.KhakiUtility.intToBytes(0b00000110) + i
                elif i == None:
                    output += self.KhakiUtility.intToBytes(0b00000111)
                else:
                    raise self.KhakiUnknownTypeException('Cannot convert type {0}'.format(type(i)))
            except OverflowError:
                vlen += 1
            else:
                ready = True
            
        return output
        
    def from_bytes(self, i: bytes):
        meta = self.KhakiUtility.META
        vlen = self.KhakiUtility.bytesToInt(i[:meta])
        type = self.KhakiUtility.bytesToInt(i[meta:meta*2])
        i = i[meta*2:]
        
        if   type == 0b00001001:
            return int(self.from_bytes(i))
        elif type == 0b00001000:
            return self.KhakiUtility.bytesToInt(i)
        elif type == 0b00000111:
            return None
        elif type == 0b00000110:
            return i
        elif type == 0b00000101:
            return struct.unpack('<?', i)[0]
        elif type == 0b00000100:
            return struct.unpack('<d', i)[0]
        elif type == 0b00000011:
            return struct.unpack('<q', i)[0]
        elif type == 0b00000010:
            return i.decode('utf8')
        elif type == 0b00000001:
            data = []
        
            while len(i) > 0:
                size = self.KhakiUtility.bytesToInt(i[:vlen])
                data.append(self.from_bytes(i[vlen:size+vlen]))
                i = i[size+vlen:]
            
            return data
        elif type == 0b00000000:
            data = {}
        
            while len(i) > 0:
                size = self.KhakiUtility.bytesToInt(i[:vlen])
                key = self.from_bytes(i[vlen:size+vlen])
                i = i[size+vlen:]
                
                size = self.KhakiUtility.bytesToInt(i[:vlen])
                value = self.from_bytes(i[vlen:size+vlen])
                i = i[size+vlen:]
                
                data[key] = value
            
            return data
        else:
            raise self.KhakiUnknownTypeException('Cannot convert an invalid type value, data stream must be invalid.')
            
class StaticKhaki:
    @staticmethod
    def dumps(*args, **kwargs):
        x = Khaki()
        return x.dumps(*args, **kwargs)
        
    @staticmethod
    def loads(*args, **kwargs):
        x = Khaki()
        return x.loads(*args, **kwargs)
    
def _main():
    # THIS IS THE BADLY WRITTEN SCRIPT USED FOR TESTING PLASMA.
    # DON'T RUN THIS.
    
    import sys
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
    
if __name__ == '__main__':
    import cProfile
    
    if DEBUG:
        cProfile.run('_main()', sort='cumtime')
    else:
        _main()