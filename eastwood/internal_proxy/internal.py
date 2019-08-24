from eastwood.protocols.ew_protocol import EWProtocol

class InternalProxyInternalProtocol(EWProtocol):
	"""
	Handles poems from the external proxy and sends them to the minecraft server, and vice versa
	"""
	def packet_recv_add_conn(self, buff):
		# Add a connection to InternalProxyMCClientFactory
		self.other_factory.add_connection(buff.unpack_uuid())

	def packet_recv_delete_conn(self, buff):
		# Delete uuid connection
		uuid = buff.unpack_uuid()
		try:
			self.other_factory.get_client(uuid).transport.loseConnection()
		except KeyError:
			pass # Already gone
		except AttributeError:
			del self.other_factory.uuid_dict[uuid.to_hex()] # Delete the reference if it is none
