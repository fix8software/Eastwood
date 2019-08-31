from twisted.internet.protocol import ReconnectingClientFactory

from eastwood.modules import Module
from eastwood.plasma import IteratedSaltedHash
from eastwood.factories.ew_factory import EWFactory
from eastwood.protocols.ew_protocol import EWProtocol

class ExternalProxyInternalModule(Module):
	"""
	Handles sending data as buffered "poems" from clients to the internal proxy and vice versa
	"""
	def connectionMade(self):
		"""
		Send auth packet, otherwise packets will be dropped
		"""
		if self.protocol.password: # If password is empty/none the auth packet will not be sent
			# Hash password
			hashed_pass, salt = IteratedSaltedHash(self.protocol.password.encode())

			data = b"".join((
				self.protocol.buff_class.pack_packet(hashed_pass), # Data is passed as packets for length prefixing
				self.protocol.buff_class.pack_packet(salt)
			))

			self.protocol.send_packet("auth", data) # Send
			self.logger.info("Sent auth packet")

	def packet_recv_release_queue(self, buff):
		"""
		Allow client with packed uuid to send packets
		"""
		uuid = buff.unpack_uuid()
		client = self.protocol.other_factory.get_client(uuid)

		# Add queued packets to buffer
		for packet_uuid, packet_name, packet_data in client.queue:
			self.protocol.factory.input_buffer.append((uuid, packet_name, packet_data))

		client.queue = None # Remove queue

class ExternalProxyInternalFactory(EWFactory, ReconnectingClientFactory):
	"""
	Quick and dirty hack to combine the ReconnectingClientFactory with the data of EWFactory
	"""
	def buildProtocol(self, addr):
		self.resetDelay() # Reset the reconnect delay
		return EWProtocol(self, self.buff_class, self.handle_direction, self.other_factory, self.config, modules=[ExternalProxyInternalModule])
