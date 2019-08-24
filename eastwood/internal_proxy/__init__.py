"""
The proxy layer after the external proxy, runs on @Naphtha's homelab (thats real cool btw)
The internal proxy's job is to recieve packets from the external proxy and emulate connections on the LAN using that
It also sends server packets back to the external proxy to be distributed to the clients
"""
from twisted.internet import reactor

from eastwood.internal_proxy.external import InternalProxyExternalFactory
from eastwood.internal_proxy.internal import InternalProxyInternalFactory
from eastwood.server_pinger import ServerPingerFactory

def create(protocol_version, host, port, mc_host, mc_port, buffer_wait, ip_forward):
	"""
	Create an instance of InternalProxyInternalProtocol which communicates with the external proxy
	Create an instance of InternalProxyExternalFactory which controls the clients to the real server
	Args:
		protocol_version: protocol specification to use
		host: internal proxy's listening ip
		port: internal proxy's istening port
		mc_host: minecraft server's ip
		mc_port: minecraft server's port
		buffer_wait: amount of time to wait before sending buffered packets (in ms)
		ip_forward: if true, forward the true ip
	"""
	# Create an instance of InternalProxyInternalFactory which communicates with the external proxy
	internal_factory = InternalProxyInternalFactory(protocol_version, "upstream", buffer_wait, ip_forward)

	# Create an instance of InternalProxyExternalFactory which controls the clients to the real server
	client_man = InternalProxyExternalFactory(protocol_version, mc_host, mc_port, ServerPingerFactory(mc_host, mc_port))

	# Assign other_factory
	internal_factory.other_factory = client_man
	client_man.other_factory = internal_factory

	reactor.listenTCP(port, internal_factory, interface=host)
