import matplotlib.pyplot as plt
from functools import reduce
import plasma, os, time, numpy as np
import lzma, zlib, bz2

x = plasma.ParallelCompressionInterface()

MIN_LEVEL = 1
MAX_LEVEL = 22
algo = x

def compress(b: bytes, l: int) -> bytes:
	return algo.compress(b, l)
	
def decompress(b: bytes) -> bytes:
	return algo.decompress(b)

def ctest(size):
	table = {}
	stable = {}
	table_size = size
	
	crand = plasma.ThreadedModPseudoRandRestrictedRand()
	data = [
		b'\x00' * size,
		os.urandom(size),
		crand.random(size)
	]
	
	for y in data:
		__ = compress(y, MIN_LEVEL)
	
	for level in range(MIN_LEVEL, MAX_LEVEL + 1):
		times = []
		sizes = []
		for y in data:
			for _ in range(2):
				s = time.time()
				__ = compress(y, level)
				t = time.time() - s
				times.append(t)
			sizes.append(len(__))
		a = sum(times) / len(times)
		b = sum(sizes) / len(sizes)
		timebyte = (a / table_size)
	
		stable[level] = b
		table[level] = (timebyte)

	return list(table.keys()), list(stable.values()), [i * 1000 * 1000 * 1000 for i in list(table.values())]

X, Y, Z = ctest(2 ** 16 - 1)
normY = [float(i)/sum(Y) for i in Y]
normY = [i * 1000 for i in normY]
plt.subplot(2, 1, 1)
plt.plot(X, Z)
plt.title('Algo: '+str(repr(algo)))
plt.ylabel('time per byte (ns/B)')

plt.subplot(2, 1, 2)
plt.plot(X, Y)
plt.xlabel('level')
plt.ylabel('size (B)')
plt.show()