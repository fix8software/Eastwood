from quarry.net.protocol import BufferUnderrun

from eastwood.modules import Module
from eastwood.plasma import IteratedSaltedHash
from eastwood.protocols.ew_protocol import EWProtocol

class InternalProxyInternalModule(Module):
	"""
	This internal module handles adding and removing pseudo clients
	"""
	def __init__(self, protocol):
		super().__init__(protocol)

		if not hasattr(self.protocol.other_factory, "cache_list"):
			self.protocol.other_factory.cache_lists = {-1: [], 0: [], 1: []} # List to keep track of cached data

	def packet_recv_add_conn(self, buff):
		# Add a connection to InternalProxyMCClientFactory
		self.protocol.other_factory.add_connection(buff.unpack_uuid())

	def packet_recv_toggle_chunk(self, buff):
		dimension = buff.unpack_varint()
		key = buff.read()

		if key in self.protocol.other_factory.cache_lists[dimension]:
			self.protocol.other_factory.cache_lists[dimension].remove(key)
		else:
			self.protocol.other_factory.cache_lists[dimension].append(key)

	def packet_recv_delete_conn(self, buff):
		# Delete uuid connection
		uuid = buff.unpack_uuid()
		try:
			self.protocol.other_factory.get_client(uuid).transport.loseConnection()
		except KeyError:
			pass # Already gone
		except AttributeError:
			del self.protocol.other_factory.uuid_dict[uuid.to_hex()] # Delete the reference if it is none

class InternalProxyInternalProtocol(EWProtocol):
	"""
	Handles poems from the external proxy and sends them to the minecraft server, and vice versa
	"""
	def create(self):
		super().create()

		self.authed = not bool(self.password) # If password is none, authentication is disabled

	def create_modules(self, modules):
		super().create_modules((InternalProxyInternalModule,) + modules)

	def packet_received(self, buff, name):
		"""
		Non AES version of parse_decrypted_packet
		"""
		if not self.secret and not self.authed:
			self.packet_special_auth(buff)
			return

		super().packet_received(buff, name)

	def parse_decrypted_packet(self, data, name):
		"""
		Treat all packets as an auth packet until the packet has been authenticated
		"""
		if not self.authed:
			self.packet_special_auth(self.buff_class(data))
			return

		super().parse_decrypted_packet(data, name)

	def packet_special_auth(self, buff):
		"""
		This packet does not get handled like standard packets to prevent a rogue client from abusing the check
		"""
		try:
			hashed_pass = buff.unpack_packet(self.buff_class).read()
			salt = buff.unpack_packet(self.buff_class).read()

			# Verify hashed pass with salt
			real_hash, salt = IteratedSaltedHash(self.password.encode(), salt)

			if real_hash == hashed_pass:
				self.authed = True
				self.logger.info("Authenticated!") # Successfully authenticated!
				return
		except BufferUnderrun:
			pass

		# Either the auth packet was not valid, or the compare was rejected, dc
		self.transport.loseConnection()
