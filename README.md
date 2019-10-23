# Eastwood ![GitHub last commit](https://img.shields.io/github/last-commit/smplite/Eastwood) ![GitHub](https://img.shields.io/github/license/smplite/Eastwood)

Eastwood is a proxy system designed to allow for the modification and optimization of Minecraft network traffic.

* You start with a Minecraft server, an internal proxy, an external proxy and a Velocity or Waterfall instance.
* The Minecraft server sends packets to the internal proxy. During setup, you'll configure the Minecraft server to prevent compression of packets, because the internal and external proxies will do that for you in a far more efficient manner.
* The external proxy should be hosted somewhere else, for example on a remote VPS, alongside an instance of Velocity and Waterfall, although Velocity is preferred.
* The client(s) should connect to the Velocity instance, which will authenticate the user with Mojang and handle individual compression of packets sent to them.
* Velocity will connect to the external proxy, and the external and internal proxies form a link between eachother that buffers every packet for a few milliseconds and sends them all at once on a regular basis, compressing them with an extremely efficient library called Plasma.
* Via the internal and external proxies, you can create modules that change the way Minecraft packets operate.
* As well as this, Eastwood allows you to utilize a cheap VPS or any other inexpensive remote hosting option to host a server anywhere, even with an expensive and/or slow internet connection. More importantly, it allows you to host multiple servers in a relatively cheap way without any of them consuming too many resources to slow down the others.
* Eastwood also allows you to offload the work of compressing Minecraft packets to another process in the mean time, which improves performance a bit, although that isn't really the intended purpose.

## Roadmap

* [x] Handle communication with the Minecraft client
* [x] Handle communication with the Minecraft server
* [x] Come up with a standard for inter-proxy communication
* [x] Compress inter-proxy communication as efficiently as possible
* [x] Handle compression on multiple processes to improve performance
* [ ] Figure out potential ways to further "optimize" chunk data
* [x] Cache chunk data on the external proxy side in-memory
* [x] Cache chunk data on the external proxy side on-disk
* [ ] Strip out certain parts of packets (such as heightmap data for chunks) and compute them on the external proxy side instead
* [ ] Reduce overhead involved with inter-proxy communication (e.g stop using strings for packet names as well as full player UUIDs)
* [ ] Find ways to improve performance on all remaining single-threaded tasks
* [ ] Improve stability by finding ways in which the proxies fail and programming systems to allow them to automatically recover
* [ ] Improve usability for other servers and use the terminal output to display nice statistics such as how much bandwidth has been saved
* [ ] Improve comments and general documentation
