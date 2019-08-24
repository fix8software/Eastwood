"""
The proxy layer after bungeecord and before the internal proxy, runs on the vps
Acts as a proxy to intercept, encode, and send minecraft packets to the internal proxy
"""
from twisted.internet import reactor

from eastwood.external_proxy.external import ExternalProxyBungeeCordFrontEndFactory
from eastwood.external_proxy.internal import ExternalProxyInternalFactory

def create(protocol_version, host, port, internal_host, internal_port, buffer_wait, max_connections):
	"""
	Does two things:
	Creates an instance of ExternalProxyInternalFactory which communicates with the internal proxy
	Creates an instance of ExternalProxyBungeeCordFrontEndFactory which communicates to the clients/bungee
	Args:
		protocol_version: protocol specification to use
		host: external proxy's listening ip
		port: external proxy's istening port
		internal_host: internal proxy's ip
		internal_port: internal proxy's port
		buffer_wait: amount of time to wait before sending buffered packets (in ms)
		max_connections: max amount of clients to accept before kicking
	"""
	# Create an instance of ExternalProxyInternalFactory which communicates with the internal proxy as a client
	internal_factory = ExternalProxyInternalFactory(protocol_version, "downstream", buffer_wait)

	# Creates an instance of ExternalProxyBungeeCordFrontEndFactory which communicates to the clients/bungee
	server = ExternalProxyBungeeCordFrontEndFactory(protocol_version, "upstream", 0, max_connections)

	# Assign other_factory
	internal_factory.other_factory = server
	server.other_factory = internal_factory

	# Call reactor
	reactor.connectTCP(internal_host, internal_port, internal_factory)
	reactor.listenTCP(port, server, interface=host)
