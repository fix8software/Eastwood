"""
The proxy layer after the external proxy, runs on @Naphtha's homelab (thats real cool btw)
The internal proxy's job is to recieve packets from the external proxy and emulate connections on the LAN using that
It also sends server packets back to the external proxy to be distributed to the clients
"""
from twisted.internet import reactor

from eastwood.factories.ew_factory import EWFactory
from eastwood.internal_proxy.external import InternalProxyExternalFactory
from eastwood.internal_proxy.internal import InternalProxyInternalProtocol
from eastwood.misc import parse_ip_port

def create(config):
	"""
	Create an instance of InternalProxyInternalProtocol which communicates with the external proxy
	Create an instance of InternalProxyExternalFactory which controls the clients to the real server
	Args:
		config: config dict
	"""
	# Create an instance of EWFactory with InternalProxyInternalProtocol which communicates with the external proxy
	internal_factory = EWFactory("upstream", config)
	internal_factory.protocol = InternalProxyInternalProtocol

	# Create an instance of InternalProxyExternalFactory which controls the clients to the real server
	client_man = InternalProxyExternalFactory(config)

	# Assign other_factory
	internal_factory.other_factory = client_man
	client_man.other_factory = internal_factory

	host, port = parse_ip_port(config["internal"]["bind"])
	reactor.listenTCP(port, internal_factory, interface=host)
