"""
     $M%%$My,           P L A S M A
     $F ]$L !M,          
     $F ]$L,,,l@g,      Naphtha's library for parallel, timed operations such as Compression
     $F ]@@@@@@@@@      and Encryption.
gg,  $F    'llll$@  ,g,  
@@@@,$F        l$@,%$$@ Contains additional utilities such as Khaki, which both help Plasma's
@@llllL        j||lll$@ more traditional components operate, but also can be used outside the
@@llll@W       #@llll$@ library for more creative purposes.
@@ll@@F        |$@@ll$@ 
@@@M $F        j$@"%@@@ Utils exposed:
''`  $F        j$@  ''` ParallelEncryptionInterface, ParallelCompressionInterface, IteratedSaltedHash
     #@gggggggg@@@      Khaki, StaticKhaki, ThreadedModPseudoRandRestrictedRand
       "*******f^^       
    
                        Requirements:
                            psutil==5.6.3
                            zstandard==0.11.1
                            pycryptodome==3.9.0
                            mmh3==2.5.1
                            multiprocess==0.70.9
                            colorama==0.4.1
                            
                        https://lotte.link/ - https://keybase.io/naphtha
"""

# All module imports
from Crypto import Random
from Crypto.Cipher import AES, ChaCha20_Poly1305
from psutil import cpu_count
from multiprocessing.pool import ThreadPool
from multiprocessing import Pool
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from threading import Thread
from secrets import token_bytes
from collections import deque
import zstandard as zstd
import zlib, time, os, hashlib, random, math, copy, bz2, functools, sys, platform
import urllib.request, mmh3, colorama, struct, re, psutil, uuid, json, socket, lzma
from multiprocess import Pool as DillPool
import dill
from typing import Dict, List

# These are the only classes that ought to be used with Plasma publicly.
__all__ = ["ParallelEncryptionInterface", "ParallelCompressionInterface", "IteratedSaltedHash", "StaticKhaki", "Khaki", "XOR", "Mursha27Fx43Fx2", "XChaCha20_Poly1305_Mursha27Fx43Fx2", "AESCrypt_Mursha27Fx43Fx2_IV12_NI"]

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
TRAINING_DATA_URL = 'https://github.com/fix8software/Eastwood/raw/master/eastwood/testdata/large_packet_sample.bin'
ALT_TRAINING_DATA_URL = 'https://github.com/fix8software/Eastwood/raw/master/eastwood/testdata/packet_samples.bin'
DIRECT_TRAINED_ZSTD = False

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
            cls.ParallelSequenceMapper = cls.__GLOBAL_POOL.map 
            # Create a function "ParallelSequenceMapper" so that the child class can map iterables to
            # the mutliprocessing pool.
        elif cls.__POOL_TYPE == 'multiprocessing':
            cls.__GLOBAL_POOL = ThreadPool(cls.__THREAD_COUNT)
            cls.ParallelSequenceMapper = cls.__GLOBAL_POOL.imap
        cls.ParallelSequenceMapperPoolSize = cls.__THREAD_COUNT # ParallelSequenceMapperPoolSize represents the amount of threads spawned.
        
        return object.__new__(cls)

class ProcessMappedObject(object):
    __POOL_TYPE = 'multiprocessing'
    __THREAD_COUNT = cpu_count()

    def __init__(self):
        super().__init__()

    def __new__(cls, *args, **kwargs):
        if cls.__POOL_TYPE == 'concurrent.futures':
            cls.__GLOBAL_POOL = ProcessPoolExecutor(max_workers = cls.__THREAD_COUNT)
            cls.ParallelSequenceMapper = cls.__GLOBAL_POOL.map
        elif cls.__POOL_TYPE == 'multiprocessing':
            cls.__GLOBAL_POOL = Pool(cls.__THREAD_COUNT)
            cls.ParallelSequenceMapper = cls.__GLOBAL_POOL.imap
        elif cls.__POOL_TYPE == 'multiprocess': # Multiprocess uses dill instead of cPickle.
            cls.__GLOBAL_POOL = DillPool(cls.__THREAD_COUNT)
            cls.ParallelSequenceMapper = cls.__GLOBAL_POOL.imap
        cls.ParallelSequenceMapperPoolSize = cls.__THREAD_COUNT
        
        return object.__new__(cls)
        
class StarmapProcessMappedObject(object):
    __THREAD_COUNT = cpu_count()

    def __init__(self):
        super().__init__()

    def __new__(cls, *args, **kwargs):
        cls.__GLOBAL_POOL = Pool(cls.__THREAD_COUNT)
        cls.ParallelSequenceMapper = cls.__GLOBAL_POOL.starmap
        cls.ParallelSequenceMapperPoolSize = cls.__THREAD_COUNT
        
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

class Khaki(object):
    """
    Universal lightweight format for encoding and decoding primitive data
    """
    __TYPES = {
        'dict' : 0b00000000,
        'list' : 0b00000001,
        'str'  : 0b00000010,
        'int'  : 0b00000011,
        'float': 0b00000100,
        'bool' : 0b00000101,
        'bytes': 0b00000110,
        'none' : 0b00000111,
        'bint' : 0b00001000,
        'vint' : 0b00001001
    }

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
        """
        Convert type to bytes
        """
    
        # Tidy up repeated stuff into single letter vars
        # Marginally harder to read but a lot prettier and
        # a lot less repetitive.
        a = self.KhakiUtility.intToBytes
        b = self.__TYPES
        c = lambda t: a(b[t])
        d = struct.pack
        e = self.to_bytes
    
        ready = False
        
        vlen = starting_vlen
        while ready == False:
            try:
                output = bytes()
                output += a(vlen)
            
                if   type(i) == dict:
                    output += c('dict')
                
                    for k, v in i.items():
                        key = e(k, starting_vlen)
                        output += a(len(key), vlen) + key
                        value = e(v, starting_vlen)
                        output += a(len(value), vlen) + value
                elif type(i) == list:
                    output += c('list')
                
                    for x in i:
                        value = e(x, starting_vlen)
                        output += a(len(value), vlen) + value
                elif type(i) == str:
                    output += c('str') + i.encode('utf8')
                elif type(i) == int:
                    try:
                        output += c('int') + d('<q', i)
                    except struct.error:
                        try:
                            output += c('bint') + a(i, 32)
                        except OverflowError:
                            output += c('vint') + e(str(i), starting_vlen)
                elif type(i) == float:
                    output += c('float') + d('<d', i)
                elif type(i) == bool:
                    output += c('bool') + d('<?', i)
                elif type(i) == bytes:
                    output += c('bytes') + i
                elif i == None:
                    output += c('none')
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
        
        b = self.__TYPES
        if   type == b['vint']:
            return int(self.from_bytes(i))
        elif type == b['bint']:
            return self.KhakiUtility.bytesToInt(i)
        elif type == b['none']:
            return None
        elif type == b['bytes']:
            return i
        elif type == b['bool']:
            return struct.unpack('<?', i)[0]
        elif type == b['float']:
            return struct.unpack('<d', i)[0]
        elif type == b['int']:
            return struct.unpack('<q', i)[0]
        elif type == b['str']:
            return i.decode('utf8')
        elif type == b['list']:
            data = []
        
            while len(i) > 0:
                size = self.KhakiUtility.bytesToInt(i[:vlen])
                data.append(self.from_bytes(i[vlen:size+vlen]))
                i = i[size+vlen:]
            
            return data
        elif type == b['dict']:
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

if DIRECT_TRAINED_ZSTD:
    ZSTD_TRAINING_POOL = cachedDownload(TRAINING_DATA_URL) + cachedDownload(ALT_TRAINING_DATA_URL)

    TRAINED_DICTIONARIES = {}
    for level in range(1, 23):
        x = zstd.ZstdCompressionDict(ZSTD_TRAINING_POOL[:8388608], dict_type=zstd.DICT_TYPE_RAWCONTENT)
        x.precompute_compress(level=level)
        TRAINED_DICTIONARIES[level] = x

    class ZStandardTrainedSimpleInterface(object):
        @staticmethod
        def compress(data: bytes, level: int = 1) -> bytes:
            x = zstd.ZstdCompressor(level = level, threads = cpu_count(), dict_data = TRAINED_DICTIONARIES[level])
            return level.to_bytes(1, byteorder=BYTE_ORDER) + x.compress(data)
            
        @staticmethod
        def decompress(data: bytes) -> bytes:
            x = zstd.ZstdDecompressor(dict_data = TRAINED_DICTIONARIES[int.from_bytes(data[:1], byteorder=BYTE_ORDER)])
            return x.decompress(data[1:])
        
class LZMASimpleInterface(object):
    @staticmethod
    def compress(data: bytes, level: int = 1) -> bytes:
        return lzma.compress(data, format = lzma.FORMAT_ALONE, preset = 1)
        
    @staticmethod
    def decompress(data: bytes) -> bytes:
        return lzma.decompress(data)

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
            cached: bool = True,            # Whether or not to cache requests.
            bz2chunk: bool = True,          # If true, split by block size. If false, split equally.
            exifdata: bool = False,         # If true, add extra information to compression payloads, e.g for calculating checksums.
            target_speed_ms: int = 120,     # Maximum time it should take to compress anything.
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
        self.__average_time = deque([0], maxlen=8)
        self.__trianed_average_too_high_sizes_max = 24
        self.__training_times = 64
        self.__trianed_average_too_high_sizes = deque([0], maxlen=self.__trianed_average_too_high_sizes_max)
        self.__trianed_average_too_high_sizes_repeat = deque([0], maxlen=self.__trianed_average_too_high_sizes_max)
        self.__compressions = 0
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
        
        self.__average_too_high_size_start = int( round ( ( self.__target_speed / 1000)  / self.__table[self.__MIN_LEVEL] ) )
        self.__average_too_high_size = self.__average_too_high_size_start
        
        self.__threads = []

        self.__threads.append(Thread(target=self.__jitter_training_reinitialization_thread))
        self.__threads[-1].daemon = True
        self.__threads[-1].start()

    def __jitter_training_reinitialization_thread(self):
        while True:
            while self.__compressions < self.__training_times:
                time.sleep(0.05)
                
            self.__compressions = 0
            
            self.__trianed_average_too_high_sizes_repeat.append(self.__average_too_high_size)
            
            if len(self.__trianed_average_too_high_sizes) >= self.__trianed_average_too_high_sizes_max:
                components = {}
                components['A'] = int( round( sum( self.__trianed_average_too_high_sizes ) / len( self.__trianed_average_too_high_sizes ) ) )
                components['B'] = int( round( sum( self.__trianed_average_too_high_sizes_repeat ) / len( self.__trianed_average_too_high_sizes_repeat ) ) )
                components['C'] = max( self.__trianed_average_too_high_sizes_repeat )
            
                self.__average_too_high_size = int( round( sum( list(components.values()) ) / len( list(components.values()) ) ) )
            else:
                self.__trianed_average_too_high_sizes.append(self.__average_too_high_size)
                self.__average_too_high_size = self.__average_too_high_size_start

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
        
        o = self.cached
        self.cached = False
        
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
    
        cache_object_name = '{0} Compression Object Cache (Device: {1}, Fortnight Timestamp: {2}, Compression Engine: {3}, Training Data: {4}, Min Level: {5}, Max Level: {6}, bz2chunk: {7}, cached: {8})'.format(
            type(self).__name__,           # Cache by compressor type
            self.fingerprint,              # Cache by device type
            round(time.time() / 1209600),  # Update cache every 14 days
            type(self.__engine).__name__,  # Cache by compression engine
            mmh3.hash(                     # Cache by training data
                StaticKhaki.dumps(
                    data,
                    
                    compressed = False,
                    min_value_length = 4
                )
            ),
            self.__MIN_LEVEL,
            self.__MAX_LEVEL,
            self.bz2chunk,
            self.cached
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
                
        self.cached = o
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
                if ((v * len(input)) * 1000) < self.__target_speed:
                    accept_level = k
        
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
        
            levels = (self.__global_level, accept_level, suggested)
        
            flevel = int( round( sum(levels) / len(levels) ) )
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
            
            if averaged > self.__target_speed + self.__target_buf and self.__global_level > self.__MIN_LEVEL:
                self.__global_level -= 0.5
            elif averaged < self.__target_speed - self.__target_buf and self.__global_level < self.__MAX_LEVEL:
                self.__global_level += 0.5
                
            if msec > self.__target_speed + self.__target_buf:
                self.__average_too_high_size = int(round((self.__average_too_high_size + len(input)) / 2))
                
            self.__compressions += 1
        
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
            bbs = 98304
            bs = (lambda x, y: y if x == 0 else x)(bbs * level, bbs)
            x = self.__chunks(input, bs)
        else:
            x = self.__chunks(input, int(round(len(input) / self.nodes)))
        
        # Then, create encapsulation arguments containing level, data and compression engine.
        # Then call the encapsulation function in the process pool.
        # Then join up the output to form a continuous string of bytes.
        return b''.join(
            self.ParallelSequenceMapper(
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
        result = b''.join(self.ParallelSequenceMapper(self.__engine.decompress, chunks))
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

ParallelCompressionInterface = _GlobalParallelCompressionInterface

def XOR(*args: List[bytes]) -> bytes:
    args = list(args)
    target_length = max(map(len, args))
    
    final = [0 for _ in range(target_length)]
    for k, v in enumerate(args):
        args[k] = (v * (target_length//len(v) + 1))[:target_length]
        for x, z in enumerate(args[k]):
            final[x] ^= z
            
    return bytes(final)
    
def KeyStream(key: bytes, amount: int = 4096) -> bytes:
    f = bytes()
    for i in range(amount):
        a = i.to_bytes(0xFF, byteorder = BYTE_ORDER)
        b = hashlib.sha1(key + XOR(a, key)).digest()
        c = XOR(*[x.to_bytes(1, byteorder = BYTE_ORDER) for x in list(XOR(mmh3.hash_bytes(key + a), mmh3.hash_bytes(a + b)))], b[:1], a[:1])
        d = XOR(mmh3.hash_bytes(a + b + c)[:1], mmh3.hash_bytes(a)[:1], b[:1])
        e = hashlib.sha1(XOR(c, d, mmh3.hash_bytes(b)[:1], a[-1:])).digest()
        
        f += XOR(e[:1], e[-1:], mmh3.hash_bytes(key + a)[:1])
        
    return f
    
def Mursha27Fx43Fx2(a: bytes, i: int = 0x0027FFFF, fi: int = 0x03FF):
    """
    Mursha27Fx43Fx2
    
    Hybrid of multiple iterations of Murmurhash3 and SHA256
    to calculate encryption keys.
    """

    b = XOR(a, mmh3.hash_bytes(a))
    for _ in range(i):
        b = mmh3.hash_bytes(b)
    
    c = XOR(b, mmh3.hash_bytes(b + a))
    for _ in range(i):
        c = mmh3.hash_bytes(c)
    
    f = XOR(c, mmh3.hash_bytes(c + b + a))
    for _ in range(fi):
        f = hashlib.sha256(f + a + b + c).digest()
    
    return f
        
class _SymmetricEncryptionAlgorithm(object):
    """
    This class must not be used outside of the Plasma library.
    """

    def __init__(self, key: bytes, pre_compute = True):
        self.key = (lambda x, y: key if not y else self.key_computation(key))(key, pre_compute)
        
    @staticmethod
    def key_computation(key: bytes) -> bytes:
        return Mursha27Fx43Fx2(KeyStream(key, amount = 8192))

class AESCrypt_Mursha27Fx43Fx2_IV12_NI(_SymmetricEncryptionAlgorithm):
    __IV_SIZE = 12
    __MODE = AES.MODE_GCM
    __AES_NI = True

    def encrypt(self, raw: bytes) -> bytes:
        iv = Random.new().read(self.__IV_SIZE)
        cipher = AES.new(self.key, self.__MODE, iv, use_aesni=self.__AES_NI)
        return iv + cipher.encrypt(raw)

    def decrypt(self, enc: bytes) -> bytes:
        iv = enc[:self.__IV_SIZE]
        cipher = AES.new(self.key, self.__MODE, iv, use_aesni=self.__AES_NI)
        return cipher.decrypt(enc[self.__IV_SIZE:])

class XChaCha20_Poly1305_Mursha27Fx43Fx2(_SymmetricEncryptionAlgorithm):
    def encrypt(self, raw: bytes) -> bytes:
        iv = Random.new().read(24)
        cipher = ChaCha20_Poly1305.new(key = self.key, nonce = iv)
        return iv + cipher.encrypt(raw)

    def decrypt(self, enc: bytes) -> bytes:
        iv = enc[:24]
        cipher = ChaCha20_Poly1305.new(key = self.key, nonce = iv)
        return cipher.decrypt(enc[24:])
        
class ParallelEncryptionInterface(StarmapProcessMappedObject):
    def __init__(self, key: bytes, algorithm = AESCrypt_Mursha27Fx43Fx2_IV12_NI):
        self.algorithm = algorithm
        self.key = _SymmetricEncryptionAlgorithm.key_computation(key)
        
    @staticmethod
    def _ec_e(a, i: bytes, k: bytes) -> bytes:
        b = a(key = k, pre_compute = False)
        capsule = b.encrypt(i)

        return len(capsule).to_bytes(SIZE_BYTES, byteorder=BYTE_ORDER) + capsule
        
    @staticmethod
    def _ec_d(a, i: bytes, k: bytes) -> bytes:
        b = a(key = k, pre_compute = False)
        return b.decrypt(i)
        
    def encrypt(self, raw: bytes) -> bytes:
        """
        Main encryption function.
        Args:
            raw: Bytes to encrypt
        """
        chunks = list(self.__chunks(raw, (lambda x: x if x != 0 else 1)(int(round(len(raw) / self.ParallelSequenceMapperPoolSize)))))
        chunks = self.ParallelSequenceMapper(self._ec_e, [(self.algorithm, chunk, self.key) for chunk in chunks])
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

        return b''.join(self.ParallelSequenceMapper(self._ec_d, [(self.algorithm, chunk, self.key) for chunk in chunks]))

    @staticmethod
    def __chunks(l, n):
        for i in range(0, len(l), n):
            yield l[i:i+n]
            
# Backwards compatibility
ParallelAESInterface = ParallelEncryptionInterface
            
# Fallback to AES on a single process for now. It performs better
# than the PEI system, of which doesn't really use multiple
# processes properly at all due to ThreadPools and the GIL.
# ParallelEncryptionInterface = AESCrypt_Mursha27Fx43Fx2_IV12_NI

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
        return b''.join(self.ParallelSequenceMapper(super().random, [math.ceil(size / self.ParallelSequenceMapperPoolSize) for _ in range(self.ParallelSequenceMapperPoolSize)]))[:size]
    
def _main():
    # Print compression time messages during test
    if globals()['DEBUG'] == False:
        colorama.init()
    globals()['DEBUG'] = True
    
    TEST_DATA = cachedDownload(TRAINING_DATA_URL)
    TEST_TIMES = 16

    compressor = ParallelCompressionInterface(exifdata = True, cached = False)
    for _ in range(TEST_TIMES):
        COMPRESSED_TEST_DATA = compressor.compress(TEST_DATA)
    for _ in range(TEST_TIMES):
        DECOMPRESSED_TEST_DATA = compressor.decompress(COMPRESSED_TEST_DATA)
        assert DECOMPRESSED_TEST_DATA == TEST_DATA
    
    print('-- Encryption Tests --')
    KEY = b'AverageKey'
    
    EncIntf = ParallelEncryptionInterface(KEY, algorithm = XChaCha20_Poly1305_Mursha27Fx43Fx2)
    StartTime = time.time()
    A = EncIntf.encrypt(TEST_DATA)
    assert EncIntf.decrypt(A) == TEST_DATA
    print('MiB/s: {0}'.format(
        ( len(TEST_DATA) / ( 1024 ** 2 ) ) / ( ( time.time() - StartTime ) * ( 1 ) )
    ))
        
    EncIntf = XChaCha20_Poly1305_Mursha27Fx43Fx2(KEY)
    StartTime = time.time()
    A = EncIntf.encrypt(TEST_DATA)
    assert EncIntf.decrypt(A) == TEST_DATA
    print('MiB/s: {0}'.format(
        ( len(TEST_DATA) / ( 1024 ** 2 ) ) / ( ( time.time() - StartTime ) * ( 1 ) )
    ))
    
    EncIntf = AESCrypt_Mursha27Fx43Fx2_IV12_NI(KEY)
    StartTime = time.time()
    A = EncIntf.encrypt(TEST_DATA)
    assert EncIntf.decrypt(A) == TEST_DATA
    print('MiB/s: {0}'.format(
        ( len(TEST_DATA) / ( 1024 ** 2 ) ) / ( ( time.time() - StartTime ) * ( 1 ) )
    ))
    
    print(XOR(b'exif', b'oxiffskgjwlgafsg'))
    
if __name__ == '__main__':
    import cProfile
    
    if DEBUG:
        cProfile.run('_main()', sort='cumtime')
    else:
        _main()
