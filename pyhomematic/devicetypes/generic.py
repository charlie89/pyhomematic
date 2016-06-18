import logging

LOG = logging.getLogger(__name__)

# Parameter operations. Just needed if we would get the paramset-descriptions to do some auto-configuration magic.
PARAM_OPERATION_READ = 1
PARAM_OPERATION_WRITE = 2
PARAM_OPERATION_EVENT = 4

PARAM_UNREACH = 'UNREACH'
PARAMSET_VALUES = 'VALUES'


class HMGeneric(object):
    def __init__(self, device_description, proxy, resolveparamsets):
        # These properties are available for every device and its channels
        self._ADDRESS = device_description.get('ADDRESS')
        LOG.debug("HMGeneric.__init__: device_description: " + str(self._ADDRESS) + " : " + str(device_description))
        self._FAMILY = device_description.get('FAMILY')
        self._FLAGS = device_description.get('FLAGS')
        self._ID = device_description.get('ID')
        self._PARAMSETS = device_description.get('PARAMSETS')
        self._PARAMSET_DESCRIPTIONS = {}
        self._TYPE = device_description.get('TYPE')
        self._VERSION = device_description.get('VERSION')
        self._proxy = proxy
        self._paramsets = {}
        self._eventcallbacks = []
        self._unreach = None
        self._name = None

    @property
    def ADDRESS(self):
        return self._ADDRESS

    @property
    def TYPE(self):
        return self._TYPE

    @property
    def PARAMSETS(self):
        return self._paramsets

    @property
    def NAME(self):
        return self._name

    @NAME.setter
    def NAME(self, name):
        self._name = name

    def setValue(self, key, value):
        """
        Some devices allow to directly set values to perform a specific task.
        """
        try:
            self._proxy.setValue(self._ADDRESS, key, value)
            return True
        except Exception as err:
            LOG.error("HMDevice.setValue: Exception: " + str(err))
            return False

    def getValue(self, key):
        """
        Some devices allow to directly get values for specific parameters.
        """
        try:
            returnvalue = self._proxy.getValue(self._ADDRESS, key)
            return returnvalue
        except Exception as err:
            LOG.error("HMDevice.setValue: Exception: " + str(err))
            return False

    def event(self, interface_id, key, value):
        """
        Handle the event received by server.
        """
        LOG.info(
                "HMGeneric.event: address=%s, interface_id=%s, key=%s, value=%s"
                % (self._ADDRESS, interface_id, key, value))
        if key == PARAM_UNREACH:
            self._unreach = value
        for callback in self._eventcallbacks:
            LOG.debug("HMDevice.event: Using callback %s " % str(callback))
            callback(self._ADDRESS, interface_id, key, value)

    def getParamsetDescription(self, paramset):
        """
        Descriptions for paramsets are available to determine what can be don with the device.
        """
        try:
            self._PARAMSET_DESCRIPTIONS[paramset] = self._proxy.getParamsetDescription(self._ADDRESS, paramset)
        except Exception as err:
            LOG.error("HMGeneric.getParamsetDescription: Exception: " + str(err))
            return False

    def updateParamset(self, paramset):
        """
        Devices should not update their own paramsets. They rely on the state of the server.
        Hence we pull the specified paramset.
        """
        try:
            if paramset:
                if self._proxy:
                    returnset = self._proxy.getParamset(self._ADDRESS, paramset)
                    if returnset:
                        self._paramsets[paramset] = returnset
                        if self.PARAMSETS:
                            if self.PARAMSETS.get(PARAMSET_VALUES):
                                self._unreach = self.PARAMSETS.get(PARAMSET_VALUES).get(PARAM_UNREACH)
                        return True
            return False
        except Exception as err:
            LOG.debug("HMGeneric.updateParamset: Exception: %s, %s, %s" % (str(err), str(self._ADDRESS), str(paramset)))
            return False

    def updateParamsets(self):
        """
        Devices should update their own paramsets. They rely on the state of the server. Hence we pull all paramsets.
        """
        try:
            for ps in self._PARAMSETS:
                self.updateParamset(ps)
            return True
        except Exception as err:
            LOG.error("HMGeneric.updateParamsets: Exception: " + str(err))
            return False

    def putParamset(self, paramset, data={}):
        """
        Some devices act upon changes to paramsets.
        A "putted" paramset must not contain all keys available in the specified paramset,
        just the ones which are writable and should be changed.
        """
        try:
            if paramset in self._PARAMSETS and data:
                self._proxy.putParamset(self._ADDRESS, paramset, data)
                # We update all paramsets to at least have a temporarily accurate state for the device.
                # This might not be true for tasks that take long to complete (lifting a rollershutter completely etc.).
                # For this the server-process has to call the updateParamsets-method when it receives events for the device.
                self.updateParamsets()
                return True
            else:
                return False
        except Exception as err:
            LOG.error("HMGeneric.putParamset: Exception: " + str(err))
            return False


class HMChannel(HMGeneric):
    def __init__(self, device_description, proxy, resolveparamsets=False):
        super().__init__(device_description, proxy, resolveparamsets)

        # These properties only exist for device-channels
        self._PARENT = device_description.get('PARENT')
        self._AES_ACTIVE = device_description.get('AES_ACTIVE')
        self._DIRECTION = device_description.get('DIRECTION')
        self._INDEX = device_description.get('INDEX')
        self._LINK_SOURCE_ROLES = device_description.get('LINK_SOURCE_ROLES')
        self._LINK_TARGET_ROLES = device_description.get('LINK_TARGET_ROLES')
        self._PARENT_TYPE = device_description.get('PARENT_TYPE')

        # We set the name to the parents address initially
        self._name = device_description.get('ADDRESS')

        # Optional properties of device-channels
        self._GROUP = device_description.get('GROUP')
        self._TEAM = device_description.get('TEAM')
        self._TEAM_TAG = device_description.get('TEAM_TAG')
        self._TEAM_CHANNELS = device_description.get('TEAM_CHANNELS')

        # Not in specification, but often present
        self._CHANNEL = device_description.get('CHANNEL')

        if resolveparamsets:
            self.updateParamsets()

    @property
    def PARENT(self):
        return self._PARENT

    @property
    def UNREACH(self):
        """ Returns true if children is not reachable """
        if self._unreach:
            return True
        return False

    def setEventCallback(self, callback):
        """
        Set additional event callbacks for the channel.
        children.
        Signature for callback-functions: foo(address, interface_id, key, value).
        """
        if hasattr(callback, '__call__'):
            self._eventcallbacks.append(callback)


class HMDevice(HMGeneric):
    def __init__(self, device_description, proxy, resolveparamsets=False):
        super().__init__(device_description, proxy, resolveparamsets)

        self.CHILDREN = {}

        # Data point information
        # "NODE_NAME": channel
        #  for Channel is Possible:
        # - NONE  / getVaule from Parent
        # - c  / getVaule from Channel dynamic
        # - 0..n / getValue from fix Channel
        self._SENSORNODE = {}
        self._BINARYNODE = {}
        self._ATTRIBUTENODE = {"RSSI_DEVICE": None}
        self._WRITENODE = {}

        # These properties only exist for interfaces themselves
        self._CHILDREN = device_description.get('CHILDREN')
        self._RF_ADDRESS = device_description.get('RF_ADDRESS')

        # We set the name to the address initially
        self._name = device_description.get('ADDRESS')

        # Optional properties might not always be present
        if 'CHANNELS' in device_description:
            self._CHANNELS = device_description['CHANNELS']
        else:
            self._CHANNELS = []

        self._PHYSICAL_ADDRESS = device_description.get('PHYSICAL_ADDRESS')
        self._INTERFACE = device_description.get('INTERFACE')
        self._ROAMING = device_description.get('ROAMING')
        self._RX_MODE = device_description.get('RX_MODE')
        self._FIRMWARE = device_description.get('FIRMWARE')
        self._AVAILABLE_FIRMWARE = device_description.get('AVAILABLE_FIRMWARE')
        self._UPDATABLE = device_description.get('UPDATABLE')
        self._PARENT_TYPE = None

    @property
    def RSSI_DEVICE(self):
        return self.getValue('RSSI_DEVICE')

    @property
    def UNREACH(self):
        """ Returns true if the device or any children is not reachable """
        if self._unreach:
            return True
        else:
            for channel, device in self.CHILDREN.items():
                if device.UNREACH:
                    return True
        return False

    @property
    def SENSORNODE(self):
        return self._SENSORNODE

    @property
    def BINARYNODE(self):
        return self._BINARYNODE

    @property
    def ATTRIBUTENODE(self):
        return self._ATTRIBUTENODE

    @property
    def WRITENODE(self):
        return self._WRITENODE

    def getAttributeData(self, name, channel=1):
        """ Returns a attribut """
        return self._getNodeData(name, self._ATTRIBUTENODE, channel)

    def getBinaryData(self, name, channel=1):
        """ Returns a binary node """
        return self._getNodeData(name, self._BINARYNODE, channel)

    def getSensorData(self, name, channel=1):
        """ Returns a sensor node """
        return self._getNodeData(name, self._SENSORNODE, channel)

    def getWriteData(self, name, channel=1):
        """ Returns a sensor node """
        return self._getNodeData(name, self._WRITENODE, channel)

    def _getNodeData(self, name, data, channel=1):
        """ Returns a data point from data"""
        if name in nodes:
            nodeChannel = data[name]
            if nodeChannel is None:
                return self.getValue(name)
            elif nodeChannel == 'c':
                nodeChannel = channel
            if nodeChannel <= self.ELEMENT:
                return self.CHILDREN[nodeChannel].getValue(name)

        LOG.error("HMDevice._getNodeData: %s not found in %s", name, data)
        return None

    def writeNodeData(self, name, data, channel=1):
        """ Returns a data point from data"""
        if name in nodes:
            nodeChannel = self.WRITENODE[name]
            if nodeChannel is None:
                return self.setValue(data)
            elif nodeChannel == 'c':
                nodeChannel = channel
            if nodeChannel <= self.ELEMENT:
                return self.CHILDREN[nodeChannel].setValue(data)

        LOG.error("HMDevice.writeNodeData: %s not found with value %s on %i",
                  name, data, nodeChannel)
        return False

    @property
    def ELEMENT(self):
        """
        Returns count of element for same functionality.
        Overwrite this value only if you have a spezial defice such as Sw2 usw.
        """
        return 1

    def setEventCallback(self, callback, bequeath=True, channel=0):
        """
        Set additional event callbacks for the device.
        Set the callback for specific channels or use the device itself and let
        it bequeath the callback to all of its children.
        Signature for callback-functions: foo(address, interface_id, key, value)
        """
        if hasattr(callback, '__call__'):
            if channel == 0:
                self._eventcallbacks.append(callback)
            elif not bequeath and channel > 0 and channel in self.CHILDREN:
                self.CHILDREN[channel]._eventcallbacks.append(callback)
            if bequeath:
                for channel, device in self.CHILDREN.items():
                    device._eventcallbacks.append(callback)
