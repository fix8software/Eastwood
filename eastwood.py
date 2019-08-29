import logging
import toml, time, random, string, sys
from eastwood import external_proxy, internal_proxy
from multiprocessing import set_start_method
from twisted.internet import reactor
from twisted.python import log
from pathlib import Path

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

def main():
	try:
		config_location = sys.argv[1]
	except IndexError:
		config_location = 'config.toml'
		
	config_file = Path(config_location)
	if not config_file.is_file():
		with open(config_location, 'w+') as j:
			j.write("""# {2} Configuration File - TOML
# template generation timestamp: {0}

# Please note that removal of any options in this file will cause
# significant unhandled exceptions. Regardless of what your prox(ies)
# are doing, you will need every option in this config file to be set
# to something.

title = "{2} Configuration File"

[global]
# Print debug info from modules like Twisted to the terminal.
# You can disable this if you really don't want this information, but
# it may make it harder to fix and understand out issues if they happen.
debug = true

# Specifies which proxies to start. (can be both, internal or external)
# Internal - {2} to Server, External - {2} to Client
# Both - Server to {2} to {2} to Client. Used only for debug
# and  general testing purposes.
type = "both"

# Authentication secret. Important if you're not using {2} across
# a VPN or you're just generally exposing {2} to the public in any
# way.
secret = "{1}"

# How long to buffer Minecraft packets into poems for, in milliseconds.
# Setting this to a higher value may improve bandwidth savings, but
# will increase ping.
buffer_ms = 25

# Protocol version to use for Minecraft packets. To see the protocol
# version of your version of Minecraft, look here...
# https://wiki.vg/Protocol_version_numbers
protocol_version = 498

# Whether or not to use IP forwarding. This is usually required for
# Bungeecord, Waterfall or Velocity.
ip_forwarding = true

[internal]
# Internal proxy bind address.
bind = "127.0.0.1:41429"

# Minecraft server address to connect to.
minecraft = "127.0.0.1:25565"

[external]
# External proxy bind address. This is what Velocity, Bungeecord
# or Waterfall should connect to. Do not connect directly, and always
# bind to 127.0.0.1 to prevent connections from anywhere other than
# the local machine.
bind = "127.0.0.1:37721"

# Internal proxy to connect to. If you're using anything other than
# the "both" mode, you're likely going to want to change this from its
# default value of 127.0.0.1:41429.
internal = "127.0.0.1:41429"

# External proxy player/connection limit. This is important, as you can
# utilize this with services like Velocity in order to create a really
# funky load-balancing system.
player_limit = 65535
""".format(time.time(), ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16)), 'Eastwood'))
		print('Config file generated at '+config_location+', please modify it.')
		return

	with open(config_location, 'r') as j:
		config = toml.loads(j.read())

	# Tell twisted to use the standard logging module
	observer = log.PythonLoggingObserver()
	observer.start()
	logging.getLogger().setLevel((lambda x: logging.WARN if False else logging.INFO)(config['global']['debug']))

	# Be sure processes are forked, not spawned
	set_start_method("fork")

	# Start proxies
	if config['global']['type'] in ("internal", "both"):
		ip, port = parse_ip_port(config['internal']['bind'])
		mc_ip, mc_port = parse_ip_port(config['internal']['minecraft'])
		internal_proxy.create(config['global']['protocol_version'], ip, port, mc_ip, mc_port, config['global']['buffer_ms'], config['global']['secret'], config['global']['ip_forwarding'])
	if config['global']['type'] in ("external", "both"):
		ip, port = parse_ip_port(config['external']['bind'])
		internal_ip, internal_port = parse_ip_port(config['external']['internal'])
		external_proxy.create(config['global']['protocol_version'], ip, port, internal_ip, internal_port, config['global']['secret'], config['global']['buffer_ms'], config['external']['player_limit'])

	# Run proxy with twisted
	reactor.run()

if __name__ == "__main__":
	main()
