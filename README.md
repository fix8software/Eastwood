# EastWood
Two proxies designed to reduce network costs for Minecraft server hosting by offloading tasks to shitty VPS

## Roadmap

* [x] Handle communication with the Minecraft client
* [x] Handle communication with the Minecraft server
* [x] Come up with a standard for inter-proxy communication
* [x] Compress inter-proxy communication with LZMA
* [x] Handle compression on multiple processes to improve performance
* [ ] Figure out potential ways to further "optimize" chunk data
* [ ] Cache chunk data on the external proxy side in-memory
* [ ] Cache chunk data on the external proxy side on-disk
* [ ] Strip out certain parts of packets (such as heightmap data for chunks) and compute them on the external proxy side instead
* [ ] Reduce overhead involved with inter-proxy communication (e.g stop using strings for packet names as well as full player UUIDs)
* [ ] Find ways to improve performance on all remaining single-threaded tasks
* [ ] Improve stability by finding ways in which the proxies fail and programming systems to allow them to automatically recover
* [ ] Improve usability for other servers and use the terminal output to display nice statistics such as how much bandwidth has been saved
* [ ] Improve comments and general documentation
