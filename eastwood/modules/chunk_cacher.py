"""
Chunk caching system to reduce the netusage of the most expensive packet to send (chunk data packets)
"""
from collections import defaultdict

from eastwood.bincache import Cache
from eastwood.modules import Module

THRESHOLD = 0 # Chunk data should be pulled x times before entering the cache (Should be greater than zero)

class ChunkCacher(Module):
	"""
	External Proxy (MCProtocol) module that intercepts and caches chunk data in ram
	Notifies the internal proxy when a chunk has been cached and should not be fully sent over the network
	Also handles requests to get chunk data from the notchian client if a chunk is already cached
	"""
	# Note for future contributers:
	# There is some outdated examples posted by the quarry dev that may help you get a wrap around this
	# https://github.com/barneygale/minebnc/blob/master/plugins/world.py
	def __init__(self, protocol):
		super().__init__(protocol)
		self.dimension = 0 # Player dimension, used for tracking chunks

		if not hasattr(self.protocol.factory, "caches"):
			self.protocol.factory.caches = {-1: Cache(), 0: Cache(), 1: Cache()} # Bincache for each dimension (-1=Nether, 0=Overworld, 1=End)
		if not hasattr(self.protocol.factory, "tracker"):
			self.protocol.factory.tracker = defaultdict(int) # Dictionary to keep track of the amount of times chunks has been pulled

	def packet_send_join_game(self, buff):
		"""
		Called when the client joins the game, we need to capture the dimension
		"""
		self.dimension = buff.unpack("ibi")[2] # Ignore entity id and gamemode

	def packet_send_respawn(self, buff):
		"""
		Same here, need to capture the dimension
		"""
		self.dimension = buff.unpack("i") # Dimension is the first packed field

	def packet_send_chunk_data(self, buff):
		"""
		Called when chunk data has been sent from the server to the client
		Chunk data can bufferunderrun. In that case, it means the chunk is cached
		and should be loaded from the cache
		"""
		# Chunk position
		chunk_x, chunk_z, full_chunk = buff.unpack("ii?") # Use the chunk x and z values in bytes as the key
		chunk_key = self.protocol.buff_class.pack("ii", chunk_x, chunk_z)

		if not full_chunk:
			# Full chunk just creates an empty chunk to be manipulated for the client. We can ignore this.
			return

		if self.protocol.factory.tracker[chunk_key] < THRESHOLD:
			# Chunk hasn't been pulled enough to warrant caching
			self.protocol.factory.tracker[chunk_key] += 1
			return

		data = buff.read() # Get rest of chunk data
		if not data:
			# There is nothing here, this means we are supposed to send a cached chunk!
			cached_data = self.generate_cached_chunk_packet(chunk_key)
			if cached_data:
				return ("chunk_data", self.protocol.buff_class(cached_data))

		# Cache it
		# The cache stores the everything in the chunk data packet after the full chunk bool
		self.protocol.factory.caches[self.dimension].insert(chunk_key, data)

		# A chunk with a tracker value > THRESHOLD will recieve chunk updates
		# This should be allowed since the data is cached
		self.protocol.factory.tracker[chunk_key] += 1

		# Tell the other protocol
		self.protocol.other_factory.instance.send_packet("toggle_chunk", b"".join((self.protocol.buff_class.pack_varint(self.dimension), chunk_key)))

	def packet_send_block_change(self, buff):
		"""
		Called when there is a single block change
		"""
		# Unpack enough to check if data is cached or not
		x, y, z = buff.unpack_position()

		# Get chunk and relative positions
		cx, bx = divmod(x, 16)
		cy, by = divmod(y, 16)
		cz, bz = divmod(z, 16)

		chunk_key = self.protocol.buff_class.pack("ii", cx, cz) # Get chunk key
		if self.protocol.factory.tracker[chunk_key] > THRESHOLD: # Check if chunk is cached (not equal to since when the threshold is equal to stored amount the chunk is actually cached)
			# Chunk is cached, update

			# Unpack rest of data
			block = buff.unpack_varint()
			self.set_blocks(chunk_key, (cy, bx, by, bz, block))

	def packet_send_multi_block_change(self, buff):
		"""
		Called when there is a multi block change
		"""
		chunk_x, chunk_z  = buff.unpack("ii") # Use the chunk x and z values in bytes as the key
		chunk_key = self.protocol.buff_class.pack("ii", chunk_x, chunk_z)

		if self.protocol.factory.tracker[chunk_key] > THRESHOLD: # Check if chunk is cached (not equal to since when the threshold is equal to stored amount the chunk is actually cached)
			# Chunk is cached, update

			# Unpack rest of data
			records = []
			for _ in range(buff.unpack_varint()):
				# Extract data from each record
				horiz_pos, vert_pos = buff.unpack("BB")
				x = horiz_pos >> 4 & 15 # Relative block positions
				cy, y = divmod(vert_pos, 16) # Need chunk and relative for y
				z = horiz_pos & 15
				block = buff.unpack_varint()

				# Append to record list
				records.append((cy, x, y, z, block))

			# Call set_blocks with data
			self.set_blocks(chunk_key, *records)

	def set_blocks(self, key, *blocks):
		"""
		Sets blocks in a cached chunk
		Args:
			key: chunk key
			blocks: tuples of (cy, x, y, z, block_id) Note that the coords are relative to the chunk (cy is the section to modify)
		"""
		sections, biomes = self.get_chunk_sections(key) # Get chunk

		for change in blocks:
			sections[change[0]][change[2]*256 + change[3]*16 + change[1]] = change[4] # Set block id
			pass

		# Save chunk section
		self.set_chunk_sections(key, sections, biomes)

	def get_chunk_sections(self, key):
		"""
		Gets cached chunk sections as a tuple
		Args:
			key: chunk column to get
		Returns:
			sections: list of BlockArray chunk sections
			biomes: list of biome data
		"""
		column = self.protocol.buff_class(self.protocol.factory.caches[self.dimension].get(key))
		prim_bit_mask = column.unpack_varint()
		column.unpack_nbt() # Ignore heightmap

		return column.unpack_chunk(prim_bit_mask) # Biome data is stored after chunk sections, this is used for repacking

	def set_chunk_sections(self, key, sections, biomes):
		"""
		Sets a cached chunk section
		Args:
			key: chunk column to save to
			sections: list of BlockArray chunk sections
			biomes: list of biome data
		"""
		column = self.protocol.buff_class(self.protocol.factory.caches[self.dimension].get(key))

		# Unpack existing data, most will be reused
		column.unpack_varint() # Old bitmask won't be used
		heightmap = column.unpack_nbt()
		column.read(length=column.unpack_varint()) # Ignore current chunk data
		tile_entity_data = column.read() # We won't mess with this

		# Repack cached data
		cached_data = b"".join((self.protocol.buff_class.pack_chunk_bitmask(sections),
							self.protocol.buff_class.pack_nbt(heightmap),
							self.protocol.buff_class.pack_chunk(sections, biomes),
							tile_entity_data))

		# Save new data
		self.protocol.factory.caches[self.dimension].insert(key, cached_data)

	def generate_cached_chunk_packet(self, key):
		"""
		Generates a chunk data packet from a key
		Args:
			key: chunk x and z
		"""
		cached_data = self.protocol.factory.caches[self.dimension].get(key)
		if cached_data == None:
			del self.protocol.factory.tracker[key] # Reset the counter since the chunk is no longer cached
			self.protocol.other_factory.send_packet("toggle_chunk", b"".join((self.protocol.buff_class.pack_varint(self.dimension), key))) # Tell the other protocol that it is no longer cached
			return None

		return b"".join((key, self.protocol.buff_class.pack("?", True), cached_data))
