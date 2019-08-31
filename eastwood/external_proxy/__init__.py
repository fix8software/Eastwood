"""
The proxy layer after bungeecord and before the internal proxy, runs on the vps
Acts as a proxy to intercept, encode, and send minecraft packets to the internal proxy
"""
from twisted.internet import reactor

from eastwood.external_proxy.external import ExternalProxyExternalFactory
from eastwood.external_proxy.internal import ExternalProxyInternalFactory
from eastwood.misc import parse_ip_port

def create(config):
	"""
	Does two things:
	Creates an instance of ExternalProxyInternalFactory which communicates with the internal proxy
	Creates an instance of ExternalProxyExternalFactory which communicates to the clients/bungee
	Args:
		config: config dict
	"""
	# Create an instance of ExternalProxyInternalFactory which communicates with the internal proxy as a client
	internal_factory = ExternalProxyInternalFactory("downstream", config)

	# Creates an instance of ExternalProxyExternalFactory which communicates to the clients/bungee
	server = ExternalProxyExternalFactory("upstream", config)

	# Assign other_factory
	internal_factory.other_factory = server
	server.other_factory = internal_factory

	# Call reactor
	internal_host, internal_port = parse_ip_port(config["external"]["internal"])
	host, port = parse_ip_port(config["external"]["bind"])
	reactor.connectTCP(internal_host, internal_port, internal_factory)
	reactor.listenTCP(port, server, interface=host)
