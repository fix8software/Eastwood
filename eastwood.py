import logging
from argparse import ArgumentParser
from eastwood import external_proxy, internal_proxy
from twisted.internet import reactor
from twisted.python import log

def parse_ip_port(string):
	"""
	Takes IP:PORT formatted string and splits the address + port, port is also casted to an int
	Args:
		string: IP:PORT formatted string
	"""
	try:
		string = string.split(":")
		return string[0], int(string[1])
	except:
		print("Invalid IP:PORT provided!")
		exit()

if __name__ == "__main__":
	parser = ArgumentParser(description="2x proxies to lower minecraft server net usage by dumping the work to a cheapo vps instead")
	parser.add_argument("type", type=str, choices=["internal", "external", "both"], help="proxy(ies) to start")
	parser.add_argument("-d", "--debug", action="store_const", const=logging.INFO, default=logging.WARN, help="enable debug for twisted")
	parser.add_argument("-iip", "--internal_proxy_ip", type=str, default="0.0.0.0:41429", metavar="IP:PORT", help="internal proxy's bind address and port (default: 0.0.0.0:41429)")
	parser.add_argument("-eip", "--external_proxy_ip", type=str, default="127.0.0.1:37721", metavar="IP:PORT", help="external proxy's bind address and port (default: 127.0.0.1:37721)")
	parser.add_argument("-r", "--remote", type=str, default="127.0.0.1:41429", metavar="IP:PORT", help="internal proxy's (used by external proxy) address and port (default: 127.0.0.1:41429)")
	parser.add_argument("-m", "--mc_server", type=str, default="127.0.0.1:25565", metavar="IP:PORT", help="minecraft server's address and port (default: 127.0.0.1:25565)")
	parser.add_argument("-b", "--buffer_wait", type=int, default=50, metavar="MS", help="time to wait before sending buffered packets in ms (default: 50 ms)")
	parser.add_argument("-p", "--protocol", type=int, default=498, metavar="VERSION", help="protocol specification to use. should be the same as the minecraft server's (default: 498 aka 1.14.4)")
	parser.add_argument("-f", "--forward_ip", action="store_true", help="if set, forwards the true ip to the server (for bungeecord)")
	args = parser.parse_args()

	# Tell twisted to use the standard logging module
	observer = log.PythonLoggingObserver()
	observer.start()
	logging.getLogger().setLevel(args.debug)

	# do_NOT_garbage_collect = []
	if args.type in ("internal", "both"):
		ip, port = parse_ip_port(args.internal_proxy_ip)
		mc_ip, mc_port = parse_ip_port(args.mc_server)
		internal_proxy.create(args.protocol, ip, port, mc_ip, mc_port, args.buffer_wait, args.forward_ip)
	if args.type in ("external", "both"):
		ip, port = parse_ip_port(args.external_proxy_ip)
		internal_ip, internal_port = parse_ip_port(args.remote)
		external_proxy.create(args.protocol, ip, port, internal_ip, internal_port, args.buffer_wait)

	# Run proxy with twisted
	reactor.run()
