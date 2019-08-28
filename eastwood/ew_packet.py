"""
Dictionary of possible packet events
Essentially copied from https://github.com/barneygale/quarry/blob/master/quarry/data/packets.py
But filled with packets eastwood uses internally instead
"""

"""
List to lookup packet metadata via id
"""
packet_names = [
	# tuple has packet name and valid towards directions (space delimited)
	("poem", "upstream downstream"),
	# packet id # 0
	# fields:
	# 	per packet:
	#		int: the order/index of the packet
	#		uuid: the user/sender of the packet
	#		byte array: the packet itself
	("delete_conn", "upstream"),
	# packet id # 1
	# fields:
	#	uuid: the user/sender to remove
	("add_conn", "upstream"),
	# packet id # 2
	# fields:
	#	uuid: the user/sender to add
	("release_queue", "downstream"),
	# packet id # 3
	# fields:
	#	uuid: the user/sender to allow sending packets
]

"""
Dictionay to lookup packet ids via name
This dictionary is auto generated
"""
packet_ids = {}
for k, v in enumerate(packet_names):
	packet_ids[v[0]] = (k, v[1])
