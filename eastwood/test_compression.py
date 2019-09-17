import matplotlib.pyplot as plt
from functools import reduce
import plasma, os, time, numpy as np

from mpl_toolkits.mplot3d import Axes3D
fig = plt.figure()
ax = fig.add_subplot(111, projection='3d')

x = plasma.ParallelCompressionInterface()

def ctest(size):
	MIN_LEVEL = 1
	MAX_LEVEL = 22

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
		__ = x.compress(y, MIN_LEVEL)
	
	for level in range(MIN_LEVEL, MAX_LEVEL + 1):
		times = []
		sizes = []
		for y in data:
			for _ in range(2):
				s = time.time()
				__ = x.compress(y, level)
				t = time.time() - s
				times.append(t)
			sizes.append(len(__))
		a = sum(times) / len(times)
		b = sum(sizes) / len(sizes)
		timebyte = (a / table_size)
	
		stable[level] = b
		table[level] = (timebyte)

	return np.array(list(table.keys())), np.array(list(stable.values())), np.array([i * 1000 * 1000 * 1000 for i in list(table.values())])

X, Y, Z = ctest(2 ** 18 - 1)
ax.plot_trisurf(X, Y, Z, linewidth=0.9, antialiased=True)
plt.ylabel('Size')
plt.xlabel('Level')
plt.show()