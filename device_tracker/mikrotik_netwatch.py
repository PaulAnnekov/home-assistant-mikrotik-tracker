"""
Support for Mikrotik routers.
For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/device_tracker.mikrotik/
"""
import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.device_tracker import (
    DOMAIN, PLATFORM_SCHEMA, DeviceScanner, CONF_SCAN_INTERVAL)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

REQUIREMENTS = ['routeros-api==0.14']

CONF_PORT = 'port'
CONF_ADDRESS_RANGE = 'address_range'
CONF_INTERFACE = 'interface'

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_HOST, default='192.168.88.1'): cv.string,
    vol.Optional(CONF_ADDRESS_RANGE): cv.string,
    vol.Optional(CONF_INTERFACE): cv.string,
    vol.Optional(CONF_PORT, default=8728): cv.string,
    vol.Optional(CONF_USERNAME, default='admin'): cv.string,
    vol.Optional(CONF_PASSWORD, default=''): cv.string,
})


def get_scanner(hass, config):
    """Validate the configuration and return MTikScanner."""
    scanner = MikrotikDeviceScanner(config[DOMAIN])
    _LOGGER.debug('Mikrotik init')
    return scanner if scanner.success_init else None


class MikrotikDeviceScanner(DeviceScanner):
    """This class queries a Mikrotik router."""

    def __init__(self, config):
        """Initialize the scanner."""
        self.last_results = None
        self.host = config[CONF_HOST]
        self.interface = config[CONF_INTERFACE]
        self.address_range = config[CONF_ADDRESS_RANGE]
        self.port = config[CONF_PORT]
        self.username = config[CONF_USERNAME]
        self.password = config[CONF_PASSWORD]
        self.scan_interval = config[CONF_SCAN_INTERVAL]
        self.success_init = True

        from routeros_api import RouterOsApiPool

        # Establish a connection to the Mikrotik router.
        connection = RouterOsApiPool(self.host, username=self.username, password=self.password, port=self.port)
        self.client = connection.get_api()
        self.leases = self.client.get_resource('/ip/dhcp-server/lease').get()
        _LOGGER.debug('Got leases %s', str(self.leases))

        # At this point it is difficult to tell if a connection is established.
        # So just check for null objects.
        if not connection.connected:
            self.success_init = False

        if self.success_init:
            _LOGGER.info('Successfully connected to Mikrotik device')

            # Reserve 2 seconds for API communication.
            self.ip_scan_args = {"duration": str(max(self.scan_interval.seconds - 2, 1))}
            if self.address_range:
                self.ip_scan_args["address-range"] = self.address_range
            if self.interface:
                self.ip_scan_args["interface"] = self.interface
            _LOGGER.debug('ip_scan_args %s', str(self.ip_scan_args))

            self._update_info()
        else:
            _LOGGER.error('Failed to establish connection to Mikrotik device with IP: %s', self.host)

    def scan_devices(self):
        self._update_info()
        active_hosts = set()
        if self.last_results is None:
            return []
        for device in self.last_results:
            mac = None
            if 'mac-address' in device:
                mac = device['mac-address']
            else:
                lease = next((item for item in self.leases if item['address'] == device['address']), None)
                if lease is not None:
                    mac = lease["mac-address"]
            # TODO: last_results can contain multiple records for same IP and some can be w/ MAC, fix this
            if mac is None:
                _LOGGER.error('Can\'t define %s IP mac address, neither ip-scan, nor DHCP Server - Leases has this '
                              'info.', device['address'])
            else:
                active_hosts.add(mac)
        _LOGGER.debug('active_hosts %s', str(active_hosts))
        return list(active_hosts)

    def get_device_name(self, mac):
        _LOGGER.debug('get_device_name "%s" "%s" "%s"', str(mac), str(self._name_from_ip_scan(mac)),
                      str(self._name_from_leases(mac)))
        return self._name_from_ip_scan(mac) or self._name_from_leases(mac)

    def _name_from_ip_scan(self, mac):
        priorities = ['netbios', 'dns', 'snmp']
        for priority in priorities:
            res = next((rec for rec in self.last_results if 'mac-address' in rec and rec['mac-address'] == mac and
                        rec[priority]), None)
            if res:
                return res[priority]
        return None

    def _name_from_leases(self, mac):
        lease = next((rec for rec in self.leases if rec['mac-address'] == mac), None)
        if not lease:
            return None
        if 'comment' in lease:
            return lease['comment']
        elif 'host-name' in lease and lease['host-name'] != {}:
            return lease['host-name']
        else:
            return None

    def _update_info(self):
        """Retrieve latest information from the Mikrotik box."""
        _LOGGER.info('Polling')
        self.last_results = self.client.get_resource('/tool').call('ip-scan', arguments=self.ip_scan_args)
        _LOGGER.info('results %s', str(self.last_results))
        return True
