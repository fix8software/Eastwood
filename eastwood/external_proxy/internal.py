from twisted.internet.protocol import ReconnectingClientFactory

from eastwood.factories.ew_factory import EWFactory
from eastwood.protocols.ew_protocol import EWProtocol

class ExternalProxyInternalProtocol(EWProtocol):
	"""
	Handles sending data as buffered "poems" from clients to the internal proxy and vice versa
	"""
	def packet_release_queue(self, buff):
		"""
		Allow client with packed uuid to send packets
		"""
		uuid = buff.unpack_uuid()
		client = self.other_factory.get_client(uuid)

		# Add queued packets to buffer
		for packet_uuid, packet_name, packet_data in client.queue:
			self.factory.input_buffer.append((uuid, packet_name, packet_data))

		client.queue = None # Remove queue

	def packet_mc_login_success(self, uuid, buff):
		"""
		Set protocol_mode to play
		https://wiki.vg/Protocol#Handshake
		"""
		client = self.other_factory.get_client(uuid)

		client.send_packet("login_success", buff.read()) # Send packet myself
		client.protocol_mode = "play" # Change mode after sending to prevent an error

		return (uuid, "login_success", None) # Prevent old packet from sending

class ExternalProxyInternalFactory(EWFactory, ReconnectingClientFactory):
	"""
	Quick and dirty hack to combine the ReconnectingClientFactory with the data of EWFactory
	"""
	def buildProtocol(self, addr):
		self.resetDelay() # Reset the reconnect delay
		return ExternalProxyInternalProtocol(self, self.buff_class, self.handle_direction, self.other_factory, self.buffer_wait)
