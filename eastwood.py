import logging
import toml, datetime, secrets, sys, os
from eastwood import external_proxy, internal_proxy
from multiprocessing import set_start_method
from twisted.internet import reactor
from twisted.python import log
from pathlib import Path
from sys import platform

def main():
	try:
		config_location = sys.argv[1]
		if not os.path.isfile(sys.argv[1]):
			config_location = 'config.toml'
	except IndexError:
		config_location = 'config.toml'

	config_file = Path(config_location)
	if not config_file.is_file():
		with open(config_location, 'w+') as j:
			j.write("""# {3} Configuration File - TOML
# template generation timestamp: {0} UTC

# Please note that removal of any options in this file will cause
# significant unhandled exceptions. Regardless of what your prox(ies)
# are doing, you will need every option in this config file to be set
# to something.

title = "{3} Configuration File"

[global]
# Print debug info from modules like Twisted to the terminal.
# You can disable this if you really don't want this information, but
# it may make it harder to fix and understand out issues if they happen.
debug = true

# Specifies which proxies to start. (can be both, internal or external)
# Internal - {3} to Server, External - {3} to Client
# Both - Server to {3} to {3} to Client. Used only for debug
# and  general testing purposes.
type = "both"

# Proxy authentication password. Important if you're not using {3} across
# a VPN or you're just generally exposing {3} to the public in any
# way. Used to authenticate proxy and allow packets to be registered
# by the other proxy. Set to "" to disable authentication.
password = "{1}"

# Shared AES secret. Also important if you're not using {3} across
# a VPN or you're just generally exposing {3} to the public in any
# way. This is used to keep traffic encrypted and prevent a MITM attack.
# Set to "" to disable AES.
secret = "{2}"

# How long to buffer Minecraft packets into poems for, in milliseconds.
# Setting this to a higher value may improve bandwidth savings, but
# will increase ping.
buffer_ms = 75

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

[chunk_caching]
# Enable chunk caching.
# Warning: This feature is experimental, and will most likely raise stupid
# amounts of exceptions. You have been warned.
enabled = false

# Chunk data should be pulled x times before entering the cache
threshold = 5

# Set the path value to a filename to enable on-disk caching. The filename will
# be postpended with the dimension and a .db filetype. Set to ":memory:" to use
# in ram caching instead. In memory is recommended, however it isn't persistant.
path = ":memory:"
""".format(datetime.datetime.now(), secrets.token_urlsafe(25), secrets.token_urlsafe(25), 'Eastwood'))
		print('Config file generated at '+config_location+', please modify it.')
		return

	with open(config_location, 'r') as j:
		config = toml.loads(j.read())

	# Tell twisted to use the standard logging module
	observer = log.PythonLoggingObserver()
	observer.start()
	logging.getLogger().setLevel((lambda x: logging.WARN if False else logging.INFO)(config['global']['debug']))

	# Be sure processes are forked, not spawned
	if platform == "linux" or platform == "linux2" or platform == "darwin":
		set_start_method("fork")

	# Start proxies
	if config['global']['type'] in ("internal", "both"):
		internal_proxy.create(config)
	if config['global']['type'] in ("external", "both"):
		external_proxy.create(config)

	# Run proxy with twisted
	reactor.run()

if __name__ == "__main__":
	main()
