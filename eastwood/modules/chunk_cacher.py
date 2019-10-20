"""
Chunk caching system to reduce the netusage of the most expensive packet to send (chunk data packets)
"""
from collections import defaultdict
from mmh3 import hash128
from twisted.internet import reactor

from eastwood.bincache import Cache
from eastwood.modules import Module
from eastwood.plasma import ParallelCompressionInterface

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
		self.threshold = self.protocol.config["chunk_caching"]["threshold"]
		self.dimension = 0 # Player dimension, used for tracking chunks

		self.plasma = ParallelCompressionInterface()

		# Factory variables that we set in this module's init
		if not hasattr(self.protocol.factory, "caches"):
			# Generate path extensions
			path0 = path1 = path2 = self.protocol.config["chunk_caching"]["path"]
			if path0 != ":memory:":
				path0 += "_nether.db"
				path1 += "_overworld.db"
				path2 += "_end.db"

			self.protocol.factory.caches = {-1: Cache(path=path0), 0: Cache(path=path1), 1: Cache(path=path2)} # Bincache for each dimension (-1=Nether, 0=Overworld, 1=End)
		if not hasattr(self.protocol.factory, "tracker"):
			self.protocol.factory.tracker = {-1: defaultdict(int), 0: defaultdict(int), 1: defaultdict(int)} # Dictionary to keep track of the amount of times chunks has been pulled
		if not hasattr(self.protocol.factory, "loaded_cache"):
			self.protocol.factory.loaded_cache = False
		if not hasattr(self.protocol.factory, "processed_packets"):
			self.protocol.factory.processed_packets = {-1: [], 0: [], 1: []} # Hashes for processed packets to prevent duplicate processing

			# Set timer to clear processed packets, this should be only called once
			# It is set to be called after 2x the buffer_wait
			reactor.callLater(self.protocol.config["global"]["buffer_ms"]/500, self.clear_processed_packets)
		if not hasattr(self.protocol.factory, "last_grabbed_key"):
			self.protocol.factory.last_grabbed_key = None
		if not hasattr(self.protocol.factory, "last_grabbed_value"):
			self.protocol.factory.last_grabbed_value = None

	def connectionMade(self):
		"""
		Loads cached chunks into the tracker
		Also sends over toggle_chunk packets for already cached chunks
		"""
		if self.protocol.factory.loaded_cache: # Should only be called once
			return

		for i in self.protocol.factory.caches.keys():
			for ident in self.protocol.factory.caches[i].get_all_identifiers():
				self.protocol.factory.tracker[i][ident] = self.threshold + 1 # Set tracker to read from it
				self.protocol.other_factory.instance.send_packet("toggle_chunk", self.protocol.buff_class.pack_varint(i), ident) # Send toggle_chunk

		self.protocol.factory.loaded_cache = True

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
			if self.is_duplicate(buff.buff): # ignore duplicate change packets only, full chunk packets are exempt
				return

			# Non full chunks act as a large multiblockchange
			if self.protocol.factory.tracker[self.dimension][chunk_key] <= self.threshold: # Check if chunk is cached
				return # Ignore uncached changes

			# Chunk bitmask
			prim_bit_mask = buff.unpack_varint()

			# TODO: Actually care about this
			buff.unpack_nbt() # Ignore heightmap data

			# Unpack cached sections
			sections, biomes = self.get_chunk_sections(chunk_key) # Get chunk
			if not sections or not biomes:
				# Data is gone! Ignore the change request
				self.handle_missing_data(chunk_key)
				return

			# Unpack changed sections
			changed_sections, _ = buff.unpack_chunk(prim_bit_mask, full_chunk, self.dimension == 0) # Varint is the bitmask

			# Apply new sections if they are not empty
			for i, new_section in enumerate(changed_sections):
				if new_section:
					sections[i] = new_section

			# Update cache
			self.set_chunk_sections(chunk_key, sections, biomes)

			# Update block entities
			tile_entities = {}
			for _ in range(buff.unpack_varint()): # Loop through every tile entity
				tile_entity = buff.unpack_nbt()
				te_obj = tile_entity.to_obj()[""]

				tile_entities[(te_obj["x"], te_obj["y"], te_obj["z"])] = tile_entity

			self.set_tile_entities(chunk_key, tile_entities)
			return

		if self.protocol.factory.tracker[self.dimension][chunk_key] < self.threshold:
			# Chunk hasn't been pulled enough to warrant caching
			self.protocol.factory.tracker[self.dimension][chunk_key] += 1
			return

		data = buff.read() # Get rest of chunk data
		if not data:
			# There is nothing here, this means we are supposed to send a cached chunk!
			cached_data = self.generate_cached_chunk_packet(chunk_key)
			if cached_data:
				return ("chunk_data", self.protocol.buff_class(cached_data))

		# Cache it
		# The cache stores the everything in the chunk data packet after the full chunk bool
		self.set_cached_chunk(chunk_key, data, insert=True)

		# A chunk with a tracker value > self.threshold will recieve chunk updates
		# This should be allowed since the data is cached
		self.protocol.factory.tracker[self.dimension][chunk_key] += 1

		# Tell the other protocol
		self.protocol.other_factory.instance.send_packet("toggle_chunk", self.protocol.buff_class.pack_varint(self.dimension), chunk_key)

	def packet_send_block_change(self, buff):
		"""
		Called when there is a single block change
		"""
		if self.is_duplicate(buff.buff):
			return # Ignore duplicates

		# Unpack enough to check if data is cached or not
		x, y, z = buff.unpack_position()

		# Get chunk and relative positions
		cx, bx = divmod(x, 16)
		cy, by = divmod(y, 16)
		cz, bz = divmod(z, 16)

		chunk_key = self.protocol.buff_class.pack("ii", cx, cz) # Get chunk key
		if self.protocol.factory.tracker[self.dimension][chunk_key] > self.threshold: # Check if chunk is cached (not equal to since when the threshold is equal to stored amount the chunk is actually cached)
			# Chunk is cached, update

			# Unpack rest of data
			block = buff.unpack_varint()
			self.set_blocks(chunk_key, (cy, bx, by, bz, block))

	def packet_send_explosion(self, buff):
		"""
		Called when there is an explosion
		"""
		# Explosion packets are unique since they also contain player data. We don't want that as we only care about the block changes
		if self.is_duplicate(buff.buff[:len(buff.buff)-32*3]):
			return # Ignore duplicates

		# Unpack explosion point
		x, y, z, _ = buff.unpack("ffff")

		# Unpack each record (they may not all be in only one chunk)
		records = defaultdict(list)
		for _ in range(buff.unpack('i')):
			dx, dy, dz = buff.unpack("bbb") # Unpack offsets for each record

			# Get chunk and relative positions
			cx, bx = divmod(x + dx, 16)
			cy, by = divmod(y + dy, 16)
			cz, bz = divmod(z + dz, 16)
			cx = int(cx)
			cy = int(cy)
			cz = int(cz)
			bx = int(bx)
			by = int(by)
			bz = int(bz)

			chunk_key = self.protocol.buff_class.pack("ii", cx, cz) # Get chunk key

			# Append to records
			records[chunk_key].append((cy, bx, by, bz, 0))

		# Call set_blocks for each chunk section
		for key, values in records.items():
			if self.protocol.factory.tracker[self.dimension][key] > self.threshold: # Check if chunk is cached (not equal to since when the threshold is equal to stored amount the chunk is actually cached)
				# Chunk is cached, update
				self.set_blocks(key, *values)

		# Player motion values are ignored

	def packet_send_multi_block_change(self, buff):
		"""
		Called when there is a multi block change
		"""
		if self.is_duplicate(buff.buff):
			return # Ignore duplicates

		chunk_x, chunk_z  = buff.unpack("ii") # Use the chunk x and z values in bytes as the key
		chunk_key = self.protocol.buff_class.pack("ii", chunk_x, chunk_z)

		if self.protocol.factory.tracker[self.dimension][chunk_key] > self.threshold: # Check if chunk is cached (not equal to since when the threshold is equal to stored amount the chunk is actually cached)
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

	def packet_send_update_block_entity(self, buff):
		"""
		Updates a tile entity, could be add modify or remove
		"""
		if self.is_duplicate(buff.buff):
			return # Ignore duplicates

		# Get enough info for the chunk key
		x, y, z = buff.unpack_position()
		chunk_key = self.protocol.buff_class.pack("ii", x // 16, z // 16) # Get chunk key

		# Check if the chunk is cached
		if self.protocol.factory.tracker[self.dimension][chunk_key] > self.threshold:
			# Get tile entities
			tile_entities = self.get_tile_entities(chunk_key)
			if not tile_entities:
				# Chunk no longer exists
				self.handle_missing_data(chunk_key)
				return

			# Unpack rest of data
			buff.unpack('B') # We don't care about the action
			new_tag = buff.unpack_nbt()
			old_tag = tile_entities.get((x, y, z))

			# Update tag
			if old_tag and not new_tag:
				del tile_entities[(x, y, z)]
			elif not old_tag and new_tag:
				tile_entities[(x, y, z)] = new_tag
			elif old_tag and new_tag:
				old_tag.update(new_tag)

			# Apply update
			self.set_tile_entities(chunk_key, tile_entities)

	def is_duplicate(self, data):
		"""
		Checks whether data has already been processed
		Args:
			data: packet data to hash and compare with
		Returns:
			bool: whether data is duplicated or not
		"""
		comp_hash = hash128(data) # Hash and check the list
		res = comp_hash in self.protocol.factory.processed_packets[self.dimension]

		if not res: # Add to the list if this is unique
			self.protocol.factory.processed_packets[self.dimension].append(comp_hash)

		return res

	def clear_processed_packets(self):
		"""
		Clears the hashes in processed_packets
		"""
		reactor.callLater(self.protocol.config["global"]["buffer_ms"]/500, self.clear_processed_packets) # Recall

		for l in self.protocol.factory.processed_packets.values():
			l.clear()

	def get_cached_chunk(self, chunk_key):
		"""
		Grabs chunk data from the cache and uncompresses it
		Args:
			chunk_key: identifier in cache
		"""
		data = self.protocol.factory.last_grabbed_value
		if chunk_key != self.protocol.factory.last_grabbed_key: # Use the last grabbed value if possible
			# Grab a new chunk
			self.protocol.factory.last_grabbed_key = chunk_key

			cached_data = self.protocol.factory.caches[self.dimension].get(chunk_key)
			if not cached_data:
				self.handle_missing_data(chunk_key)
				return None

			# Uncompress
			data = self.protocol.factory.last_grabbed_value = self.plasma.decompress(cached_data)

		# Return
		return self.protocol.buff_class(data)

	def set_cached_chunk(self, chunk_key, data, insert=False):
		"""
		Compresses data and sets it in the cache
		Args:
			chunk_key: identifier in cache
			data: bytes object
			insert: whether to insert or update, only use insert if you are adding new data
		"""
		# update last set value
		self.protocol.factory.last_grabbed_key = chunk_key
		self.protocol.factory.last_grabbed_value = data

		# Compress and set!
		func = self.protocol.factory.caches[self.dimension].insert if insert else self.protocol.factory.caches[self.dimension].update
		func(chunk_key, self.plasma.compress(data))

	def set_blocks(self, key, *blocks):
		"""
		Sets blocks in a cached chunk
		Args:
			key: chunk key
			blocks: tuples of (cy, x, y, z, block_id) Note that the coords are relative to the chunk (cy is the section to modify)
		"""
		sections, biomes = self.get_chunk_sections(key) # Get chunk
		if not sections or not biomes:
			# Data is gone! Ignore the change request
			self.handle_missing_data(key)
			return

		for change in blocks:
			sections[change[0]][0][change[2]*256 + change[3]*16 + change[1]] = change[4] # Set block id

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
		column = self.get_cached_chunk(key)
		if not column:
			return (None, None)

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
		column = self.get_cached_chunk(key)
		if not column:
			return

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
		self.set_cached_chunk(key, cached_data)

	def generate_cached_chunk_packet(self, key):
		"""
		Generates a chunk data packet from a key
		Args:
			key: chunk x and z
		"""
		cached_data = self.get_cached_chunk(key)
		if not cached_data:
			return None

		return b"".join((key, self.protocol.buff_class.pack("?", True), cached_data.buff))

	def get_tile_entities(self, key):
		"""
		Gets block entities as a dictionary of nbt tags
		Args:
			key: chunk key
		Returns:
			dict: tile entities as nbt tags, or None if chunk is no longer cached
		"""
		# Get cached chunk
		chunk = self.get_cached_chunk(key)
		if not chunk:
			return None

		# Read through all the unimportant stuff
		chunk.unpack_varint()
		chunk.unpack_nbt()
		chunk.read(chunk.unpack_varint())

		# Parse the nbt data
		tile_entities = {}
		for _ in range(chunk.unpack_varint()): # Loop through every tile entity
			tile_entity = chunk.unpack_nbt()
			te_obj = tile_entity.to_obj()[""]

			tile_entities[(te_obj["x"], te_obj["y"], te_obj["z"])] = tile_entity

		return tile_entities

	def set_tile_entities(self, key, tile_entities):
		"""
		Applies tile_entities to a cached chunk
		Args:
			key: chunk key
			tile_entities: tile entities as nbt tags
		"""
		column = self.get_cached_chunk(key)
		if not column:
			return

		# Get other chunk data
		prim_bit_mask = column.unpack_varint()
		heightmap = column.unpack_nbt()
		chunk_data = column.read(length=column.unpack_varint())
		column.read() # Ignore chunk data

		# Repack cached data with new tile entity data
		cached_data = b"".join((self.protocol.buff_class.pack_varint(prim_bit_mask),
							self.protocol.buff_class.pack_nbt(heightmap),
							self.protocol.buff_class.pack_varint(len(chunk_data)),
							chunk_data,
							self.protocol.buff_class.pack_varint(len(tile_entities)),
							*[self.protocol.buff_class.pack_nbt(e) for e in tile_entities.values()]))

		# Save new data
		self.set_cached_chunk(key, cached_data)

	def handle_missing_data(self, key):
		"""
		Call when chunk data is missing from the database
		"""
		del self.protocol.factory.tracker[self.dimension][key] # Reset the counter since the chunk is no longer cached
		self.protocol.other_factory.instance.send_packet("toggle_chunk", self.protocol.buff_class.pack_varint(self.dimension), key)
