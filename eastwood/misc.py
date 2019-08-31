def parse_ip_port(string):
	"""
	Takes IP:PORT formatted string and splits the address + port, port is also casted to an int
	Args:
		string: IP:PORT formatted string
	"""
	string = string.split(":")
	return string[0], int(string[1])
