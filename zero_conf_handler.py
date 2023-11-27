import collections
import logging
import sys
import threading
import time

import zeroconf
import socket
from typing import Union
import netifaces
import netaddr


def to_bytes(
    s_or_u: Union[str, bytes], encoding: str = "utf-8", errors: str = "strict"
) -> bytes:
    """
    Make sure ``s_or_u`` is a byte string.

    Arguments:
        s_or_u (str or bytes): The value to convert
        encoding (str): encoding to use if necessary, see :meth:`python:str.encode`
        errors (str): error handling to use if necessary, see :meth:`python:str.encode`
    Returns:
        bytes: converted bytes.
    """
    if s_or_u is None:
        return s_or_u

    if not isinstance(s_or_u, (str, bytes)):
        s_or_u = str(s_or_u)

    if isinstance(s_or_u, str):
        return s_or_u.encode(encoding, errors=errors)
    else:
        return s_or_u

def _format_zeroconf_service_type(service_type):
    if not service_type.endswith("."):
        service_type += "."
    if not service_type.endswith("local."):
        service_type += "local."
    return service_type


def _format_zeroconf_name(name, service_type):
    service_type = _format_zeroconf_service_type(service_type)
    return f"{name}.{service_type}"


def _format_zeroconf_server_name(server_name):
    if not server_name.endswith("."):
        server_name += "."
    return server_name


def _format_zeroconf_txt(record):
    result = {}
    if not record:
        return result

    for key, value in record.items():
        result[to_bytes(key)] = to_bytes(value)
    return result


def interface_addresses(family=None, interfaces=None, ignored=None):
    """
    Retrieves all the host's network interface addresses.
    """

    if not family:
        family = netifaces.AF_INET

    if interfaces is None:
        interfaces = netifaces.interfaces()

    if ignored is not None:
        interfaces = [i for i in interfaces if i not in ignored]

    for interface in interfaces:
        try:
            ifaddresses = netifaces.ifaddresses(interface)
        except Exception:
            continue
        if family in ifaddresses:
            for ifaddress in ifaddresses[family]:
                address = netaddr.IPAddress(ifaddress["addr"])
                if not address.is_link_local() and not address.is_loopback():
                    yield ifaddress["addr"]


def get_interface_addresses(family=None, interfaces=None, ignored=None):
    return list(
        interface_addresses(family, interfaces, ignored)
    )


class ZeroConfHandler:
    def __init__(self, name=None, port=None, _logger=None):
        self._zeroconf = zeroconf.Zeroconf(get_interface_addresses())
        self._zeroconf_registrations = collections.defaultdict(list)
        self._logger = _logger or logging.getLogger(__name__)
        self.name = name or "Server on {}".format(socket.gethostname())
        self.port = port or 8080

    def zeroconf_register(self, service_type, name=None, port=None, txt_record=None, server_url=None, address=None):
        """
        Registers a new service with Zeroconf/Bonjour/Avahi.

        :param service_type: type of service to register, e.g. "_http._tcp"
        :param name: displayable name of the service, if not given defaults to the instance name
        :param port: port to register for the service, if not given defaults to a (public) port
        :param txt_record: optional txt record to attach to the service, dictionary of key-value-pairs
        :param server_url: optional server name to register for the service.
        :param address: optional address to register for the service, if not given defaults to the host's address
        """

        name = name or self.name
        port = port or self.port

        service_type = _format_zeroconf_service_type(service_type)
        name = _format_zeroconf_name(name, service_type)
        txt_record = _format_zeroconf_txt(txt_record)

        key = (service_type, port)

        if address:
            addresses = [address]
        else:
            addresses = get_interface_addresses()

        addresses = list(map(socket.inet_aton, addresses))

        if not server_url:
            server_name = f"{socket.gethostname()}.local."
        else:
            server_name = _format_zeroconf_server_name(server_url)

        try:
            info = zeroconf.ServiceInfo(
                service_type,
                name,
                addresses=addresses,
                port=port,
                server=server_name,
                properties=txt_record,
            )
            self._zeroconf.register_service(info, allow_name_change=True)
            self._zeroconf_registrations[key].append(info)
            
            self._logger.debug(info)
            self._logger.debug(f"Registered '{name}' for {service_type}")
        except Exception:
            self._logger.exception("Could not register {name} for {service_type} on port {port}")

    def zeroconf_unregister(self, service_type, port=None):
        """
        Unregisters a previously registered Zeroconf/Bonjour/Avahi service identified by service and port.

        :param service_type: the type of the service to be unregistered
        :param port: the port of the service to be unregistered, defaults to a (public) port if not given
        :return:
        """

        port = port or self.port

        service_type = _format_zeroconf_service_type(service_type)

        key = (service_type, port)
        if key not in self._zeroconf_registrations:
            return

        infos = self._zeroconf_registrations.pop(key)
        try:
            for info in infos:
                self._zeroconf.unregister_service(info)
            self._logger.debug(f"Unregistered {service_type} on port {port}")
        except Exception:
            self._logger.exception(f"Could not (fully) unregister {service_type} on port {port}")

    def zeroconf_browse(
            self, service_type, block=True, callback=None, browse_timeout=5, resolve_timeout=5
    ):
        """
        Browses for services on the local network providing the specified service type. Can be used either blocking or
        non-blocking.

        The non-blocking version (default behaviour) will not return until the lookup has completed and
        return all results that were found.

        For non-blocking version, set `block` to `False` and provide a `callback` to be called once the lookup completes.
        If no callback is provided in non-blocking mode, a ValueError will be raised.

        The results are provided as a list of discovered services, with each service being described by a dictionary
        with the following keys:

          * `name`: display name of the service
          * `host`: host name of the service
          * `post`: port the service is listening on
          * `txt_record`: TXT record of the service as a dictionary, exact contents depend on the service

        Callbacks will be called with that list as the single parameter supplied to them. Thus, the following is an
        example for a valid callback:

            def browse_callback(results):
              for result in results:
                print "Name: {name}, Host: {host}, Port: {port}, TXT: {txt_record!r}".format(**result)

        :param service_type: the service type to browse for
        :param block: whether to block, defaults to True
        :param callback: callback to call once lookup has completed, must be set when `block` is set to `False`
        :param browse_timeout: timeout for browsing operation
        :param resolve_timeout: timeout for resolving operations for discovered records
        :return: if `block` is `True` a list of the discovered services, an empty list otherwise (results will then be
                 supplied to the callback instead)
        """

        if not block and not callback:
            raise ValueError("Non-blocking mode but no callback given")

        service_type = _format_zeroconf_service_type(service_type)

        result = []
        result_available = threading.Event()
        result_available.clear()

        class ZeroconfListener:
            def __init__(self, _logger=None):
                self._logger = _logger or logging.getLogger(__name__)

            def add_service(self, zeroconf, type, name):
                info = zeroconf.get_service_info(
                    type, name, timeout=resolve_timeout * 1000
                )
                if info:

                    def to_result(info, address):
                        n = info.name[: -(len(type) + 1)]
                        p = info.port

                        self._logger.debug(
                            "Resolved a result for Zeroconf resolution of {}: {} @ {}:{}".format(
                                type, n, address, p
                            )
                        )

                        return {
                            "name": n,
                            "host": address,
                            "port": p,
                            "txt_record": info.properties,
                        }

                    for address in map(lambda x: socket.inet_ntoa(x), info.addresses):
                        result.append(to_result(info, address))

            def update_service(self, zeroconf, type, name):
                pass

            def remove_service(self, zeroconf, type, name):
                pass

        self._logger.debug(f"Browsing Zeroconf for {service_type}")

        def browse():
            listener = ZeroconfListener()
            browser = zeroconf.ServiceBrowser(self._zeroconf, service_type, listener)
            time.sleep(browse_timeout)
            browser.cancel()

            if callback:
                callback(result)
            result_available.set()

        browse_thread = threading.Thread(target=browse)
        browse_thread.daemon = True
        browse_thread.start()

        if block:
            result_available.wait()
            return result
        else:
            return []

if __name__ == "__main__":
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)
    logging.basicConfig(stream=sys.stdout, level=logging.WARNING)
    logging.basicConfig(stream=sys.stderr, level=logging.CRITICAL)
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)

    conf = ZeroConfHandler()
    conf.zeroconf_register("_http._tcp", "Testing", 80)
    conf.zeroconf_browse("_http._tcp")
