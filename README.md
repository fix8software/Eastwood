# Eastwood ![GitHub last commit](https://img.shields.io/github/last-commit/smplite/Eastwood) ![GitHub](https://img.shields.io/github/license/smplite/Eastwood)

<img src="https://gamepedia.cursecdn.com/minecraft_gamepedia/a/a8/Oak_Tree.png?version=cfa8e90489d840a3ab9655b16234b098" align="right"
     title="Minecraft Gamepedia Wiki Spruce Tree" width="120">

Eastwood is a proxy system designed to allow for the modification and optimization of Minecraft network traffic.

* You start with a Minecraft server, an **internal proxy**, an **external proxy** and a Velocity or Waterfall instance.
* The Minecraft server sends packets to the *internal proxy*. During setup, you'll configure the Minecraft server to prevent compression of packets, because the internal and external proxies will do that for you in a far more **efficient** manner.
* The *external proxy* should be hosted somewhere else, for example on a remote VPS, alongside an instance of Velocity and Waterfall, although Velocity is preferred.
* The client(s) should connect to the Velocity instance, which will authenticate the user with Mojang and handle individual compression of packets sent to them.
* Velocity will connect to the *external proxy*, and the external and internal proxies form a link between eachother that **buffers every packet** for a few milliseconds and sends them all at once on a regular basis, compressing them with an extremely efficient library called **Plasma**. All the traffic for every player is **compressed together**, which is a lot more efficient than the communication between Velocity or Waterfall and the Minecraft server.
* Via the internal and external proxies, you can create modules that **change the way Minecraft packets operate**.
* As well as this, Eastwood allows you to utilize a cheap VPS or any other inexpensive remote hosting option to host a server **anywhere**, even with an expensive and/or slow internet connection. More importantly, it allows you to host **multiple servers** in a **relatively cheap** way without any of them consuming too many resources to slow down the others.
* Eastwood also allows you to offload the work of compressing Minecraft packets to **another process** in the mean time, which improves performance a bit, although that isn't really the intended purpose.

## Eastwood Plugin
In addition to the proxy system, it is likely there will also be a Bukkit plugin soon that will utiltize ProtocolLib, mainly for the purposes of removing information from chunk data that the user can't see as well as other assorted netcode improvements.

We're not quite sure how we intend to implement this yet, but if it works, it will make the experience much smoother for clients on large servers, as well as making the server itself run anywhere between a bit smoother and way smoother.

## Setup

In order to complete setup, you will need anywhere between 2 and 4 virtual machines and/or bare metal computers. In this guide, we will assume that you have 4 of them, although always consider that System A and System B can run on the same machine as well as System C and System D having the ability to run on the same machine. Think of them like services, although A and B cannot mix with C and D on the same machine, otherwise there's no point in running Eastwood.

The optimal use case for Eastwood would be if you ran systems A and B on your local area network and C and D in the cloud (e.g on a VPS).

In this guide, it will be assumed that all of the systems listed below are running on a Linux distribution.
* **System A** - The Minecraft Server
* **System B** - Eastwood Internal Proxy
* **System C** - Eastwood External Proxy
* **System D** - Velocity or Waterfall *(Velocity in this demonstration)*

1. Edit `server.properties` on *System A* and change `network-compression-threshold` to `-1`. This will disable compression on the Minecraft server, as it'll be a waste of resources considering all of the proxies (Eastwood and Velocity) will do it in the server's place.
2. Assuming you use Paper or Spigot, edit `spigot.yml` on *System A* and change `bungeecord` to `true`. This will allow Velocity or Waterfall to send the correct UUID of each client as well as their correct IP to the server.
3. On *System B* and *System C*, run `git clone https://github.com/smplite/Eastwood.git && cd Eastwood`.
4. Install `python3` and `python3-pip` on *System B* and *System C* with your favourite package manager. Those are not guaranteed to be the package names on your system. On Ubuntu 18.04+, the command would be `sudo apt update && sudo apt install python3 python3-pip`.
5. Assuming you are in the `Eastwood` directory on *System B* and *System C*, run `pip3 install -r requirements.txt` and `python3 eastwood.py`. You will be told on both systems that a configuration file has been generated. Edit `config.toml` with `vim config.toml` on both systems and use the comments in the config file(s) to set Eastwood up on both systems appropriately.
6. When Eastwood is configured on *System B* and *System C*, taking extra care to make sure that *System B* has the `type` value set to `internal` and *System C* has the `type` value set to `external`, you may run the proxies on both *System B* and *System C* with `python3 eastwood.py` again. If you have `debug` set to `true` in the config files and Eastwood does not print `Connected to the other proxy!`, you have not followed the guidelines in the config files properly. Make sure the IPs in the `[internal]` and `[external]` sections on both sides are correct.
7. Follow Velocity's guide(s) on how to install Velocity on *System D* [here](https://www.velocitypowered.com/).
8. Configure Velocity to use the legacy/bungeecord authentication mode and place the IP and port of *System C* in the config file as one of the servers Velocity should try to connect to.
9. When you finally run Velocity on *System D*, again using the "Getting Started" guide on their website, you should be able to connect to the Velocity instance and, assuming everything works correctly, you should be connected through *D* to *C*, then to *B* and then to *A*.

## Eastwood Utilities

During Eastwood's development, many components of Eastwood such as Plasma were designed to be re-usable and configurable for other purposes. If you would like to use Plasma in your own code, that's awesome! Just don't forget to take the appropriate steps outlined in the [License](https://github.com/smplite/Eastwood/blob/master/LICENSE).

### Plasma
*Click [here](https://github.com/smplite/Eastwood/blob/master/eastwood/plasma.py) to jump to the file!*

There are a few neat utilities in Plasma you could use, such as:
* **ParallelCompressionInterface** - A high efficiency compression system that aims for both high speed and high compression ratio. It's called wanting to have your cake *and* eat it.
* **Khaki** - A data format for storing primitive types, similar in use to Minecraft's NBT.
* **ThreadedModPseudoRandRestrictedRand** - A class for generating both random *and* compressable data. Initially used to test the *ParallelCompressionInterface*.
* **IteratedSaltedHash** - A function for creating secure password hashes when the *bcrypt* module is not available.

## Roadmap

* [x] Handle communication with the Minecraft client
* [x] Handle communication with the Minecraft server
* [x] Come up with a standard for inter-proxy communication
* [x] Compress inter-proxy communication as efficiently as possible
* [x] Handle compression on multiple processes to improve performance
* [x] Cache chunk data on the external proxy side in-memory
* [x] Cache chunk data on the external proxy side on-disk
* [ ] Reduce overhead involved with inter-proxy communication (e.g stop using strings for packet names as well as full player UUIDs)
* [ ] Find ways to improve performance with everything outside of the Plasma library
* [ ] Improve stability of the proxies and design them to be able to cope with a few more different scenarios such as, for example, what the external proxy should do when the internal proxy crashes and restarts.
* [ ] Improve usability for other servers and use the terminal output to display nice statistics such as how much bandwidth has been saved, what modules are loaded, etc.
* [ ] Improve comments and general documentation
* [ ] Make a serverside plugin that does some of the work we initially planned for Eastwood to do, such as not sending parts of chunks that are not visible. Many ore-obfuscators have similar code to do this, so it wouldn't be hard to figure out how to do it.
