
''' 
Created on January 16, 2016 V1.0

@author: Mark Kopache
The programs receives temperatures and gives commands to the Arduinos that controls the
thermostats in the house. 
see Thermostat controls document for crosswalk of coils to arduino pins to relays to zones
MODBUS master(server) over TCP/IP
This program communicates with Thermostatctrl.ino for the arduino. Version should be the same.
This program also monitors water temperatures in the heating system and makes decision based on those temps.
V1.0-3.8
    Non-curses base and basically not Object Oriented.
v4.0 November 25, 2018
    Curses based, partially Object Oriented 
v4.1 December 7, 2018
    Automatic house temp control using round robin heat
v4.2 December 12, 2018 
    Implement logging 
v4.3 December 18, 2018 
    Improve coil reads  
v4.4 December 21, 2018
    Separate Auto display to it's own window with additional data display
v4.5 January 18, 2019
    Setup Setback function to set back and up during night, 
    send text message to check wood
v4.6 February 21, 2019
    Added configuration file to override configurable parameters
    Added additional modbus errors
    Change exit shortcut to e. 
v4.7 March 20, 2019
    combine the two Froling room Arduinos into one, added modbus exceptions 
v4.8 April 14, 2019
    Change setback to only set up and back based on presets. 
    Added time to text message for adding wood.
v4.9 Nov. 24, 2019
    Show bad house thermosensor reading via color red
    new "if" statement to check that response is of correct class. If not, 
       log and bypass this iteration 
v4.10 Feb. 12, 2020       
    Add weather report 
	Perform error checks on commands (numbers, etc)
'''
from time import sleep
from time import time
from datetime import datetime, timedelta, time
from pymodbus.client.sync import ModbusTcpClient
from pymodbus.exceptions import *
import smtplib
import curses
from curses import wrapper
from collections import deque
import logging
import sys
import ConfigParser
import string
import requests, json, pytemperature    # for weather reporting

# essentially constants ======================================================================
VERSION = "V4.10"
PROPANE_BYPASS_STATUS = ["Propane", "Tanks", "Preheat"]
SYSTEM_STATE_NAMES = [" ", "Heating Up Tank ",  # for bypassing the propane boiler
                      "Going ON Tank   ", "On Tank         ",
                      "Going ON Propane", "On Propane      "]
FROLING_BOILER_STATES = ["FAULT       ", "Boiler off  ",  # from Froling manual
                         "Heating up  ", "Heating     ", "Slumber     ", "Off         ",
                         "Door open   ", "Preparation ", "Pre-heating "]
emailTimes = ['08', '10', '12', '14', '20']  # emails sent at these hours
validZoneNumbers = []  # list of zones (such as [2,3,4])
LOWER_HOUSE_TEMP_F = 55.0  # house temps in this range
UPPER_HOUSE_TEMP_F = 72.0
VALID_WATER_LOWER_TEMP = 40  # heat system temps in this range
VALID_WATER_UPPER_TEMP = 190
MINIMUM_WAIT = 10.0 * 60     # AUTO : translates to minutes
SET_POINT_RANGE = 0.3        # AUTO : +/- this value
ZONE_COMFORT = [65.2, 64.7, 66.2]  # AUTO : modify these values for initial auto zone temps
MAX_ZONE_TIME = [13,10,7]    # AUTO : maximum amount of time that each zone should run on auto
END_RETURN_TEMP = 110.0      # AUTO : temp to stop pump and switch to another zone, or wait 
LOW_FLUE = 320
onBypass = False
goNow = False
autoMode = False
# V4.5 send text or mail
OVER_LOW_FLUE = False
MSG_SENT = False
FRO_HEATING = 3
WOOD_TEXT_TO = ['5186694715@txt.att.net']
# V4.5 thermostat setback function
SETBACK_ENABLE = True
SETBACK_START = 23
SETBACK_END = 6
SETBACK_AMOUNT = 2.0
SETBACK_ON = False
ZONE_SETBACK = []
setupTime = datetime.now()       # needs to be set once at time of setback
#  V4.10   weather parameters
api_key = "8225a89b62e959463e517d4260f8c927"
base_url = "http://api.openweathermap.org/data/2.5/forecast?"
complete_url = base_url + "appid=" + api_key + "&zip=12153,us"
estLowTemp = 100
estWeather = "No Data"
estLowTime = ""

# =======================================================================================================
# holds data relevant for one house zone
class houseZone(object):
    def __init__(self, name, number, cTime):
        global validZoneNumbers
        self.zoneName = name
        self.zoneNumber = number
        self.setPoint = 62.0                 
        self.currentTemp = 99.1
        self.coilValue = 0  # 0=off, 1=on
        self.pexTemp = 0.0
        self.bypass = 0  # bypass of wall thermostats on or off (only valid in [0])
        self.coil = 0  # zone pump on? 0=no, 1=yes
        self.slabCoil = 0
        self.boilroomCoil = 0
        self.cycleTime = cTime
        self.startCycleTime = datetime.now()  # initialization only
        self.endCycleTime = datetime.now()  # initialization only
        self.inCycle = False
        validZoneNumbers.append(number)  # constant in program to validate commands using zone number

    def getName(self):
        return self.zoneName

    def getNumber(self):
        return self.zoneNumber

    def getCycleTime(self):
        return self.cycleTime

    def setPexTemp(self, val):
        if val > VALID_WATER_LOWER_TEMP and val < VALID_WATER_UPPER_TEMP:
            self.pexTemp = val

    def getPexTemp(self):
        return self.pexTemp

    def setCurrentTemp(self, val):
        if val > VALID_WATER_LOWER_TEMP and val < VALID_WATER_UPPER_TEMP:
            self.currentTemp = val
        if self.currentTemp < self.setPoint - SET_POINT_RANGE:  # time to turn on
            self.setInCycle(True)
        elif self.currentTemp > self.setPoint + SET_POINT_RANGE:  # time to turn off
            self.setInCycle(False)

    def getCurrentTemp(self):
        return self.currentTemp

    def setSetPoint(self, val):
        self.setPoint = val

    def getSetPoint(self):
        return self.setPoint

    def setCoil(self, val):
        self.coil = val

    def getCoil(self):
        return self.coil

    def setBypass(self, val):
        global onBypass
        if val == 1:
            onBypass = True  # global if bypass of house wall thermostats is on/off
        else:
            onBypass = False
        self.bypass = val

    def getBypass(self):
        return self.bypass

    def setBoilroomCoil(self, val):
        self.boilroomCoil = val

    def getBoilroomCoil(self):
        return self.boilroomCoil

    def setSlabCoil(self, val):
        self.slabCoil = val

    def getSlabCoil(self):
        return self.slabCoil

    def setStartCycleTime(self, val):
        self.startCycleTime = val

    def getStartCycleTime(self):
        return self.startCycleTime

    def setEndCycleTime(self, val):
        self.endCycleTime = val

    def getEndCycleTime(self):
        return self.endCycleTime

    def setInCycle(self, val):
        self.inCycle = val

    def getInCycle(self):
        return self.inCycle


# =========================================================================================================
# 0bject to hold all house zone information objects as a list
class houseZones(object):
    def __init__(self):
        self.zones = [houseZone("2-Oak Room", "2", MAX_ZONE_TIME[0] * 60), 
                      houseZone("3-Music Room", "3", MAX_ZONE_TIME[1] * 60),
                      houseZone("4-2nd Floor", "4", MAX_ZONE_TIME[2] * 60)]
        self.autoZones = []  # zones needing heat are kept in list, [0] is one being serviced
        self.endReturnTemp = END_RETURN_TEMP

    # ---------------------------------------------------------------------------------------------------------
    #  This method controls the automatic cycling of zones heat based on time running and return temp.
    def DoAutoZoneControl(self, houseReturnTemp, dataControl):
        startNextZone = False
        #   check to see if service zone is done and turn off and pop from list
        if len(self.autoZones) > 0:
            serviceZone = self.zones[int(self.autoZones[0]) - 2]  # zone being serviced
            if not serviceZone.getInCycle():  # no longer needs heat
                dataControl.setHouseZoneOff(serviceZone.getNumber(), self)  # shut if off, pop next
                elapseTime = (datetime.now() - serviceZone.getStartCycleTime()).seconds
                logging.info('AUTO : ' + serviceZone.getNumber() + ',' + str(elapseTime) + ' on->off, ['
                             + str(houseReturnTemp) + '],' + str(self.autoZones))
                serviceZone.setEndCycleTime(datetime.now())  # should be done in maintainList
        startNextZone = self.MaintainList(dataControl)  # add new and delete old in list of zones to cycle
        if len(self.autoZones) > 0:  # not an empty list of zones
            serviceZone = self.zones[int(self.autoZones[0]) - 2]  # zone being serviced
            elapseTime = (datetime.now() - serviceZone.getStartCycleTime()).seconds  # time it's been running
            if startNextZone:
                self.OnZone(serviceZone, dataControl)
                logging.info('AUTO : ' + serviceZone.getNumber() + ' off->on, [' + str(houseReturnTemp) + '],'
                             + str(self.autoZones))
                startNextZone = False
            elif len(self.autoZones) == 1:  # this zone in wait state
                if serviceZone.getCoil():  # already turned on
                    # check to see if needs to be turned off
                    if self.TimeToTurnOff(serviceZone, elapseTime, houseReturnTemp):
                        startNextZone = self.OffZone(serviceZone, dataControl)
                        logging.info('AUTO : ' + serviceZone.getNumber() + ',' + str(elapseTime) + ' on->off, [' + str(
                            houseReturnTemp) + '],' + str(self.autoZones))
                else:  # must be in single zone wait state
                    if startNextZone or (datetime.now() - serviceZone.getEndCycleTime()).seconds > MINIMUM_WAIT:
                        elapseTime = (datetime.now() - serviceZone.getEndCycleTime()).seconds 
                        logging.info('AUTO : ' + serviceZone.getNumber() + ',' + str(
                            elapseTime) + ' off->on, MINIMUM_WAIT done,' + str(self.autoZones))
                        self.OnZone(serviceZone, dataControl)  # wait is over
                        startNextZone = False
                        # otherwise, just keep going with this zone
            elif self.TimeToTurnOff(serviceZone, elapseTime, houseReturnTemp):  # multizone zone switch
                startNextZone = self.OffZone(serviceZone, dataControl)
                logging.info(
                    'AUTO : ' + serviceZone.getNumber() + ' switching zones, [' + str(houseReturnTemp) + '] ' + str(
                        self.autoZones))
                serviceZone = self.zones[int(self.autoZones[0]) - 2]  # zone being serviced, this causes next stmt to go
        if startNextZone:
            self.OnZone(serviceZone, dataControl)
        return

    # adds to the list of zones being serviced        
    def MaintainList(self, dataControl):
        newZone = False
        currentZone = "X"
        zoneLength = len(self.autoZones)  # to see if a new zone added
        if zoneLength == 1:  # special case of 1 zone
            currentZone = self.autoZones[0]
        for zone in reversed(self.zones):
            try:
                idx = self.autoZones.index(zone.getNumber())  # already in list?
                if not zone.getInCycle():  # in list but no more heat needed
                    self.autoZones.pop(idx)  # pop any that don't need heat anymore
                    if len(self.autoZones) > 0:
                        if not (self.zones[int(self.autoZones[0]) - 2].getCoil()):
                            newZone = True
            except ValueError:  # not in list
                if zone.getInCycle():  # zone not in list, and needs heat so
                    self.autoZones.append(zone.getNumber())  # add to list
                if len(self.autoZones) == 1 and not (self.zones[int(self.autoZones[0]) - 2].getCoil()):
                    # print "this is the bugger"
                    newZone = True
        # below covers the special case where there is one zone in the list that is in a wait state 
        if len(self.autoZones) == 1 and self.autoZones[0] == currentZone:  # no zone added, special case 1 zone
            newZone = False
        if len(self.autoZones) == 0:  # empty list just to be sure
            newZone = False
        return newZone

    def OffZone(self, serviceZone, dataControl):
        dataControl.setHouseZoneOff(serviceZone.getNumber(), self)  # turn off pump
        self.autoZones.append(self.autoZones[0])  # move to the end
        self.autoZones.pop(0)
        serviceZone.setEndCycleTime(datetime.now())
        # print "in OFF zone for " + serviceZone.getNumber()
        if len(self.autoZones) == 1:
            return False
        else:
            return True

    def OnZone(self, serviceZone, dataControl):
        dataControl.setHouseZoneOn(serviceZone.getNumber(), self)
        serviceZone.setStartCycleTime(datetime.now())
        # print "in ON zone for " + serviceZone.getNumber()
        return True

    def TimeToTurnOff(self, serviceZone, elapseTime, houseReturnTemp):
        if (elapseTime > serviceZone.getCycleTime()) or (
                # return temp is above limit near end of cycle (50%)                
                (elapseTime > (serviceZone.getCycleTime() * 0.5)) and
                (houseReturnTemp >= self.endReturnTemp)):
            return True
        return False

    # =============================================================================================================


# holds data relevant to one system zone, ie heat producing/delivery(upper), heat holding(mid), or heat return(lower)
class systemZone(object):
    def __init__(self, name):
        self.zoneName = name
        self.Froling = 62.0  # boiler temp
        self.FroPipe = 62.0  # pipes to and from the Froling (mid is outside temp)
        self.FroTank = 62.0  # what the Froling thinks the tank temps are
        self.Tank = 62.0
        self.House = 62.0
        self.FrolingTank = 62.0
        self.SlabReturn = 62.0
        self.Flue = 0
        self.FrolingStatus = 0
        self.state = 0

    def getName(self):
        return self.zoneName

    def getZoneNumber(self):
        return self.zoneNumber

    def getFroPipe(self):
        return self.FroPipe

    def setFroPipe(self, val):
        if self.zoneName == 'Mid':        # outside temp is stored here & has no lower limit
            self.FroPipe = val        #    V4.9 fix
        elif VALID_WATER_LOWER_TEMP < val < VALID_WATER_UPPER_TEMP:
            self.FroPipe = val

    def getTank(self):
        return self.Tank

    def setTank(self, val):
        if VALID_WATER_LOWER_TEMP < val < VALID_WATER_UPPER_TEMP:
            self.Tank = val

    def getHouse(self):
        return self.House

    def setHouse(self, val):
        if VALID_WATER_LOWER_TEMP < val < VALID_WATER_UPPER_TEMP:
            self.House = val

    def getSlabReturn(self):
        return self.SlabReturn

    def setSlabReturn(self, val):
        if VALID_WATER_LOWER_TEMP < val < VALID_WATER_UPPER_TEMP:
            self.SlabReturn = val

    def getFroling(self):
        return self.Froling

    def setFroling(self, val):
        if VALID_WATER_LOWER_TEMP < val < VALID_WATER_UPPER_TEMP:
            self.Froling = val

    def getFrolingTank(self):
        return self.FrolingTank

    def setFrolingTank(self, val):
        if VALID_WATER_LOWER_TEMP < val < VALID_WATER_UPPER_TEMP:
            self.FrolingTank = val

    def getFlue(self):
        return self.Flue

    def setFlue(self, val):
        self.Flue = val

    def getFrolingStatus(self):
        return self.FrolingStatus

    def setFrolingStatus(self, val):
        self.FrolingStatus = val

    def setState(self, val):
        self.state = val

    def getState(self):
        return self.state


# =============================================================================================
# a list of system zone information objects
class systemZones(object):
    def __init__(self):
        self.zones = [systemZone("Upper"), systemZone("Mid"), systemZone("Lower")]

    # ================================== Modbus stuff =============================================


class MBclient(ModbusTcpClient):
    '''
    Class for MODBUS slave points
    '''

    def __init__(self, *args, **kwargs):
        ''' Constructor
        
        default modbus port is 502'''
        # ip address
        self.addr = args[0]

        ModbusTcpClient.__init__(self, self.addr)

        self.connect()

    def readCoil(self, coil):
        '''returns single read of coil value'''

        return self.read_coils(coil, 1).bits[0]

    def readCoils(self, coil, number):
        '''returns multiple read of coil value'''
        return self.read_coils(coil, number)

    def writeCoil(self, coil, val):
        '''writes value to single coil'''
        val2 = self.readCoil(coil + 1)  # **** this is a work around *******
        val3 = self.readCoil(coil + 2)  # write_coils does multiples coils and write_coil
        val4 = self.readCoil(coil + 3)  # doesn't work
        self.write_coils(coil, [val, val2, val3, val4])
        #  self.write_coil(coil, val)

    def toggleCoil(self, coil):
        '''toggles the current value of a single coil'''
        val = self.read_coils(coil, 1).bits[0]
        if type(val) is not bool:
            '''throw exception'''
            print 'communications problem, return read is:', val
        else:
            self.writeCoil(coil, (not val))

    '''    if coil == 2:
           print " toggleCoil val is ", not val
           print " in toggle, after 2 ",therm_client.readCoil(2)'''

    def readReg(self, reg, val):
        '''reads a register value'''
        return self.read_holding_registers(reg, val, unit=1)


class MBserver(object):
    '''
    Class for MODBUS master controllers
    '''

    def __init__(self, *args, **kwargs):
        '''
        Constructor
        '''
        # dictionary of Modbus slave classes
        self.clients = kwargs.pop("clients")


# ============================================== end Modbus ====================
# -----------------------------------------------------------------------------------------------------------------
# get data from Arduinos via Modbus and map to data holding areas
class dataReadWrite(object):
    #   constructor defines clients, server, and initially fills data 
    def __init__(self, dataHouse, dataSystem, buffer):
        self.therm_client = MBclient('192.168.1.51')  # thermistors - house room temps and coils
        #self.tarm_client = MBclient('192.168.1.52')   tarmroom thermistors combined with Froling in 4.7
        self.heat_client = MBclient('192.168.1.53')  # basement production, aka Main Controller
        self.froling_client = MBclient('192.168.1.54')  # Froling production
        self.master = MBserver(
            clients={1: self.therm_client, 2: self.froling_client, 3: self.heat_client }
        )
        responseClass = self.master.clients[1].readReg(3,1)            #V4.9
        self.regResponseClassName = responseClass.__class__.__name__   #V4.9
        responseCoilClass =  self.master.clients[3].readCoils(1, 2)    #V4.9
        self.coilResponseClassName = responseCoilClass.__class__.__name__   #V4.9
        singleCoilClass = self.master.clients[1].readCoil(1)            #V4.9
        self.singleCoilClassName = singleCoilClass.__class__.__name__   #V4.9
        self.getData(dataHouse, dataSystem, buffer)
        self.getCoils(dataHouse, dataSystem, buffer)
        #  heat_client = MBclient('192.168.10.152')    # basement test             

    def getData(self, myHouseHeating, myHeatSystem, buffer):
        try:                                                      # House temp control
            response = self.master.clients[1].readReg(3, 6)
        except ConnectionException:
            updateMessage(win3,"Error on : room thermistors",buffer)
            logging.info("Connection error on zone room thermistors")
        except ModbusIOException:
            updateMessage(win3,"Mbus IO Error : House temps",buffer)
            logging.info("Modbus I/O error on House Temp Arduino thermistors")
        except:
            updateMessage(win3,"Mbus Error : House temps",buffer)
            logging.info("Unknown error on House Arduino thermistors")
        else:
            if response.__class__.__name__ ==  self.regResponseClassName :   # V4.9
                myHouseHeating.zones[0].setCurrentTemp(response.registers[0]/10.0)  # zone 2 current temp
                myHouseHeating.zones[1].setCurrentTemp(response.registers[1]/10.0)  # zone 3 current temp
                myHouseHeating.zones[2].setCurrentTemp(response.registers[2]/10.0)  # zone 4 current temp
                myHouseHeating.zones[0].setPexTemp(response.registers[3]/10.0)  # zone 2 pex temp
                myHouseHeating.zones[1].setPexTemp(response.registers[4]/10.0)  # zone 3 pex temp
                myHouseHeating.zones[2].setPexTemp(response.registers[5]/10.0)  # zone 4 pex temp
            else:
                logging.info("Caught class error on House Arduino thermistors")

        try:                                                    # Main Arduino in basement
            response3 = self.master.clients[3].readReg(3, 7)
        except ConnectionException:
            updateMessage(win3,"Error on : Main temps",buffer)
            logging.info("Connection error on Main Arduino thermistors")
        except ModbusIOException:
            updateMessage(win3,"Mbus IO Error : Main temps",buffer)
            logging.info("Modbus I/O error on Main Arduino thermistors")
        except:
            updateMessage(win3,"Mbus Error : Main temps",buffer)
            logging.info("Unknown error on Main Arduino thermistors")
        else:
            if response3.__class__.__name__ ==  self.regResponseClassName :   # V4.9
                myHeatSystem.zones[0].setTank(response3.registers[0]/10.0)
                myHeatSystem.zones[1].setTank(response3.registers[1]/10.0)
                myHeatSystem.zones[2].setTank(response3.registers[2]/10.0 )
                myHeatSystem.zones[0].setHouse(response3.registers[3]/10.0)  # heat to house
                myHeatSystem.zones[2].setHouse(response3.registers[4]/10.0)  # heat return from house
                myHeatSystem.zones[0].setSlabReturn(response3.registers[5]/10.0)  # heat return from slab
                myHeatSystem.zones[0].setState(response3.registers[6])  # heating system status (propane, tanks, etc)
            else:
                logging.info("Caught class error on Main Arduino thermistors")
                
        try:                                                   # Arduino in Froling Room
            response2 = self.master.clients[2].readReg(3, 9)
        except ConnectionException:
            updateMessage(win3,"Error on : Froling registers",buffer)
            logging.info("Connection error in Froling Controller")
        except ModbusIOException:
            updateMessage(win3,"Mbus IO Error : Froling Arduino",buffer)
            logging.info("Modbus I/O error on Froling Arduino")
        except:
            updateMessage(win3,"Mbus Error : Froling temps",buffer)
            logging.info("Unknown error on Froling Arduino thermistors")
        else:
            if response2.__class__.__name__ ==  self.regResponseClassName :   # V4.9
                myHeatSystem.zones[0].setFroling(response2.registers[0])  # Boiler Temperature
                myHeatSystem.zones[0].setFlue(response2.registers[1])
                myHeatSystem.zones[0].setFrolingStatus(response2.registers[3])
                myHeatSystem.zones[0].setFrolingTank(response2.registers[4])  # upper temperature
                myHeatSystem.zones[2].setFrolingTank(response2.registers[5])  # Lower temperature
                myHeatSystem.zones[2].setFroPipe(response2.registers[6]/10.0)  # return
                myHeatSystem.zones[0].setFroPipe(response2.registers[7]/10.0)  # supply
                myHeatSystem.zones[1].setFroPipe(response2.registers[8]/10.0)  # outside temp
            else:
                logging.info("Caught class error on Froling Arduino thermistors")

    def getCoils(self, myHouseHeating, myHeatSystem, buffer):
        try:
            val = self.master.clients[1].readCoil(1)  # is bypass on or off
        except ConnectionException:
            updateMessage(win3,"Error on : house temp coils",buffer)
            logging.info("Connection error on getting bypass coil")
        except ModbusIOException:
            updateMessage(win3,"Error on : house temp coils",buffer)
            logging.info("Modbus I/O error on getting bypass coil")
        except:
            updateMessage(win3,"Error on : house temp coils",buffer)
            logging.info("Unknown error on getting bypass coil")
        else:
            if val.__class__.__name__ ==  self.singleCoilClassName :   # V4.9
                myHouseHeating.zones[0].setBypass(val)
            else:
                logging.info("Caught class error on House Temp Coils")
            
        try: 
            val = self.master.clients[3].readCoils(1, 2)  # is slab or Froling room floor pumps on or off
        except ConnectionException:
            updateMessage(win3,"Error on : Main coils",buffer)
            logging.info("Connection error on getting coils from Main Controller")
        except ModbusIOException:
            updateMessage(win3,"Error on : Main coils",buffer)
            logging.info("Modbus I/O error on getting coils from house temp client")
        except:
            updateMessage(win3,"Error on : Main coils",buffer)
            logging.info("Unknown error on getting coils from house temp client")
        else:
            if val.__class__.__name__ ==  self.coilResponseClassName :   # V4.9
                myHouseHeating.zones[0].setSlabCoil(val.bits[0])
                myHouseHeating.zones[0].setBoilroomCoil(val.bits[1])
            else:
                logging.info("Caught class error on Misc pump Coils")
                
        try:
            val = self.master.clients[1].readCoils(2, 3)  # individual zone coils
        except ConnectionException:
            updateMessage(win3,"Error on : house temp coils",buffer)
            logging.info("Connection error on getting coils from house temp client")
        except ModbusIOException:
            updateMessage(win3,"Error on : house temp coils",buffer)
            logging.info("Modbus I/O error on getting coils from house temp client")
        except:
            updateMessage(win3,"Error on : house temp coils",buffer)
            logging.info("Unknown error on getting coils from house temp client")
        else:
            if val.__class__.__name__ ==  self.coilResponseClassName :   # V4.9
                i = 0
                while i < 3:
                    myHouseHeating.zones[i].setCoil(val.bits[i])
                    i += 1
            else:
                logging.info("Caught class error on zone pump Coils")
                    

    def setBypassOn(self, houseData):
        houseData.zones[0].setBypass(1)
        self.therm_client.writeCoil(1, True)

    def setBypassOff(self, houseData):
        houseData.zones[0].setBypass(0)
        self.therm_client.writeCoil(1, False)  # and shut off the bypass relays
        for i in range(int(houseData.zones[0].getNumber()), 5):  # and shut off all temp control relays
            self.therm_client.writeCoil(i, False)

    def setHouseZoneOn(self, zone, houseData):
        self.therm_client.writeCoil(int(zone), True)
        houseData.zones[int(zone) - 2].setCoil(1)

    def setHouseZoneOff(self, zone, houseData):
        self.therm_client.writeCoil(int(zone), False)
        houseData.zones[int(zone) - 2].setCoil(0)

    def setSlabOn(self, slabNo, houseData):  # works for basement slab and Froling room slab
        if slabNo == 1:
            self.heat_client.writeCoil(1, True)  # turn slab pump on
            houseData.zones[0].setSlabCoil(1)
        else:
            self.heat_client.writeCoil(2, True)  # turn Bioler room slab pump on
            houseData.zones[0].setBoilroomCoil(1)

    def setSlabOff(self, slabNo, houseData):
        if slabNo == 1:
            self.heat_client.writeCoil(1, False)  # turn slab pump off
            houseData.zones[0].setSlabCoil(0)
            win1.addstr(1, 63, "         ")
            win1.addstr(2, 65, "      ")
        else:
            self.heat_client.writeCoil(2, False)  # turn Boiler room slab pump off
            houseData.zones[0].setBoilroomCoil(0)
            win1.addstr(4, 63, "              ")

        # -------------------------------------------------------------------------------------------------------


class messageBuffer(object):
    def __init__(self):
        # self.buf = deque([datetime.now().strftime("%H:%M ")+"System is starting"])
        self.buf = deque([])

    def addMessage(self, message):
        t = datetime.now()
        if len(self.buf) > 5:
            self.buf.popleft()
        self.buf.append(t.strftime("%H:%M:%S ") + message + "\n")

'''
   for sending mail
'''
class Gmail(object):
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.server = 'smtp.gmail.com'
        self.port = 587
        session = smtplib.SMTP(self.server, self.port)        
        session.ehlo()
        session.starttls()
        session.ehlo
        session.login(self.email, self.password)
        self.session = session

    def send_message(self, to, subject, body):
        ''' This must be removed '''
        headers = [
            "From: " + self.email,
            "Subject: " + subject,
            "To: " + to,                   # either email or text address (e.g. ##etc@txt.att.net)
            "MIME-Version: 1.0",
           "Content-Type: text/html"]
        headers = "\r\n".join(headers)
        try:
            self.session.sendmail(
              self.email,
              to,
              headers + "\r\n\r\n" + body)
            MSG_SENT = True
        except SMTPHeloError or SMTPSenderRefused:
            logging.info("SMTP failed Helo or refused")
        except:
            logging.info("SMTP fail : unknown reason")
        finally:
            self.session.quit()       
        
    # ================================================ end Class definitions =================================


def defineScreens(stdscr, myHouseZones):
    global win1, win2, win3, win4, win5
    ver = "House Status " + VERSION
    begin_x = 0;
    begin_y = 0
    height = 8;
    width = 80
    win1 = stdscr.subwin(height, width, begin_y, begin_x)
    win1.border()
    win1.addstr(0, 30, ver)  # Title
    win1.addstr(1, 1, "Zone           Current    Set Pt.   Status     Pex")
    win1.addstr(6, 51, "Heat State: ")
    for zone in myHouseZones.zones:
        win1.addstr(int(zone.getNumber()), 1, zone.getName())
    win1.refresh()

    win2 = stdscr.subwin(8, 80, 8, 0)
    win2.border()
    win2.addstr(0, 32, "System Status")
    win2.addstr(1, 1, "         Froling    Tank Pipes    FrTank   MyTank    House")
    win2.addstr(2, 1, "Upper")
    win2.addstr(3, 1, "Mid       - - -       - - -       - - -              - - - ")
    win2.addstr(4, 1, "Lower     - - -")
    win2.addstr(6, 1, "Flue Temp : ")
    win2.addstr(6, 25, "Boiler State : ")
    win2.refresh()

    win3 = stdscr.subwin(8, 40, 16, 0)  # message window
    win3.border()
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
    win3.addstr(0, 16, "Message", curses.color_pair(1))
    win3.refresh()

    win4 = stdscr.subwin(8, 39, 16, 41)
    buildCommandWindow(win4)

    win5 = stdscr.subwin(4, 80, 24, 0)  # for Auto mode only
    stdscr.refresh()


def buildCommandWindow(win):
    win.border()
    win.addstr(0, 16, "Command")
    win.addstr(1, 1, "(H)elp, (E)xit, or (C)ommand:")
    win.refresh()


#   this is real data for the house, top windows
def displayHouseData(win, myHouseHeating, myHeatSystem):
    global onBypass, autoMode, win5
    global estLowTemp, estWeather, estLowTime 
    for zone in myHouseHeating.zones:  # display house heating values
        yval = int(zone.getNumber())
        if zone.getPexTemp() > 100.0:
            colorVal = 2  # yellow
        else:
            colorVal = 1  # green
        if zone.getCurrentTemp() == 99.1:               # V4.9
            colorTemp = 3  # red
        else:
            colorTemp = 1  # green
        win.addstr(yval, 17, "{:>5.1f}".format(zone.getCurrentTemp()), curses.color_pair(colorTemp))
        win.addstr(yval, 27, "{:>5.1f}".format(zone.getSetPoint()), curses.color_pair(1))
        win.addstr(yval, 47, "{:>5.1f}".format(zone.getPexTemp()), curses.color_pair(colorVal))
        if zone.getCoil() == 0:
            val = "OFF"
            colorVal = 1
        else:
            val = "ON "
            colorVal = 2
        win.addstr(yval, 38, val, curses.color_pair(colorVal))

    stateNumber = myHeatSystem.zones[0].getState()
    if stateNumber > 0 and stateNumber < 7:  # state from arduino should be 1 to 6
        state = SYSTEM_STATE_NAMES[stateNumber]
    else:
        state = "Out of Range"
    colorNumber = 1
    if stateNumber == 5:
        colorNumber = 2
    win.addstr(6, 63, state, curses.color_pair(colorNumber))
    if myHouseHeating.zones[0].getBypass() == 1:  # bypass on?
        onBypass = True
        str1 = "Bypass is ON                          "
        colorNumber = 3
    else:
        str1 = "Bypass is OFF, Wall Thermostats ON  "
        colorNumber = 2
    win.addstr(6, 1, str1, curses.color_pair(colorNumber))
    win.addstr(1,60, "Outside:")
    win.addstr(1,69, "{:>5.1f}".format(myHeatSystem.zones[1].getFroPipe()))   # outside temp
    win.addstr(2,60, "Low/24 :")
    win.addstr(2,69, "{:>5.1f}".format(estLowTemp))            # next 24 hrs estimated low temp
    win.addstr(3,60, "Low Time:")
    win.addstr(3,69, estLowTime)
    win.addstr(4,60, "                   ")   # clear previous entry
    win.addstr(4,60, estWeather )
    if autoMode:
        win.addstr(6, 34, "                 ")  # clear list info
        win.addstr(6, 20, "Auto Cycle ON: " + str(myHouseHeating.autoZones), curses.color_pair(2))
        win5.addstr(2, 12, "                       ")  # clear list info
        win5.addstr(2, 4, "Zone Queue" + str(myHouseHeating.autoZones), curses.color_pair(2))
        waitTime = "     "
        onTime = "     "
        if len(myHouseHeating.autoZones) > 0:
            serviceZone = myHouseHeating.zones[int(myHouseHeating.autoZones[0]) - 2]  # zone currently being serviced
            if serviceZone.getCoil():
                onTime = dtFormat(serviceZone.getStartCycleTime(), datetime.now())
            if len(myHouseHeating.autoZones) == 1 and not (serviceZone.getCoil()):   # is zone in a wait state?
                waitTime = dtFormat(serviceZone.getEndCycleTime(), datetime.now())
        win5.addstr(1, 13, "     ")
        win5.addstr(1, 4, "ON Time: " + onTime)
        win5.addstr(1, 20, "Wait Time: " + waitTime)
        win5.refresh()
    elif onBypass:
        win.addstr(6, 20, "                              ")
    if myHouseHeating.zones[0].getSlabCoil() == 1:  # slab on
        win.addstr(1, 63, "Slab On", curses.color_pair(2))
        win.addstr(2, 65, "{}".format(myHeatSystem.zones[0].getSlabReturn()), curses.color_pair(2))
    if myHouseHeating.zones[0].getBoilroomCoil() == 1:  # slab on
        win.addstr(4, 63, "Boiler Room On", curses.color_pair(2))
    win.refresh()

#  format the elapsed time to minutes:seconds
def dtFormat(start, end):
    elapseTime = (end - start).seconds
    minutes = elapseTime // 60
    seconds = elapseTime - minutes * 60
    return "{:0>2}:{:0>2}".format(minutes, seconds)


#   this data for the heat part of the system, second windows    
def displaySystemData(stdscr, win, myHeatSystem):
    win.addstr(2, 11, "{:>4.0f}".format(myHeatSystem.zones[0].getFroling()), curses.color_pair(1))
    win.addstr(2, 24, "{:>4.0f}".format(myHeatSystem.zones[0].getFroPipe()), curses.color_pair(1))
    win.addstr(4, 24, "{:>4.0f}".format(myHeatSystem.zones[2].getFroPipe()), curses.color_pair(1))
    win.addstr(2, 35, "{:>4.0f}".format(myHeatSystem.zones[0].getFrolingTank()), curses.color_pair(1))
    win.addstr(4, 35, "{:>4.0f}".format(myHeatSystem.zones[2].getFrolingTank()), curses.color_pair(1))
    win.addstr(2, 45, "{:>4.0f}".format(myHeatSystem.zones[0].getTank()), curses.color_pair(1))
    win.addstr(3, 45, "{:>4.0f}".format(myHeatSystem.zones[1].getTank()), curses.color_pair(1))
    win.addstr(4, 45, "{:>4.0f}".format(myHeatSystem.zones[2].getTank()), curses.color_pair(1))
    win.addstr(2, 54, "{:>4.0f}".format(myHeatSystem.zones[0].getHouse()), curses.color_pair(1))
    win.addstr(4, 54, "{:>4.0f}".format(myHeatSystem.zones[2].getHouse()), curses.color_pair(1))
    fieldColor = 1
    if myHeatSystem.zones[0].getFlue() < LOW_FLUE:  # V4.2
        fieldColor = 2
    win.addstr(6, 14, "{:>4.0f}".format(myHeatSystem.zones[0].getFlue()), curses.color_pair(fieldColor) | curses.A_REVERSE)
    stateNumber = myHeatSystem.zones[0].getFrolingStatus()
    if stateNumber > -1 and stateNumber < 9:
        state = FROLING_BOILER_STATES[stateNumber]
    else:
        state = "Out of Range"
    win.addstr(6, 38, state, curses.color_pair(1))
    win.refresh()


def updateMessage(win, message, buffer):
    buffer.addMessage(message)
    i = 1
    colorVal = 0
    parsed = message.strip().split(" ")
    if parsed[0] == "Error":            # severe error highlighted
        colorVal = 3
    for msg in buffer.buf:
        msg = msg.rstrip()
        win.addstr(i, 1, '{0: <32}'.format(msg), curses.color_pair(colorVal))  # format message to write over previous
        i += 1
    win3.refresh()


def displayTimer(win, startTime):
    countDown = 60 - (datetime.now() - startTime).seconds
    if onBypass:  # only matters is on bypass
        win.addstr(6, 23, '{0: <15}'.format("Setpoint in " + str(countDown)))
        win.move(1, 30)
        win.refresh()
    return countDown


def UpdateAutoDisplay(win):
    win.refresh()


def BuildAutoDisplay(win):
    win.border()
    win.addstr(0, 30, "Auto Thermostats", curses.color_pair(2))  # Title
    win.refresh()


def doCommands(win, myHouseHeating, datacomm):
    global onBypass
    win.move(1, 30)
    ch = win.getch()
    if ch > 0 and ch < 255:
        cmd = chr(ch)
        cmd = cmd.upper()
        # win.addstr(cmd)
        win.refresh()
        if cmd == 'E':
            if onBypass:
                BypassShutdown(myHouseHeating, datacomm)  # check for bypass and request shutoff
            return False
        elif cmd == 'H':
            displayHelp(win4)
        else:
            curses.echo()
            win.addstr(3, 1, "command->", curses.color_pair(3))
            win.refresh()
            win.timeout(10000)  # wait for read 20 seconds
            cmmdStr = win.getstr(3, 10)
            syntaxError = ExecCommands(cmmdStr, myHouseHeating, datacomm)
            if syntaxError <> "command done":
                win.addstr(5, 1, syntaxError)
                win.addstr(6, 1, "Hit any key")
                win.refresh()
                ch = win.getch()
            curses.noecho
            win.timeout(0)  # unblock
        win.clear()
        buildCommandWindow(win4)  # reset window
    return True


def ExecCommands(line, myHouseHeating, datacomm):
    global onBypass, validZoneNumbers, LOWER_HOUSE_TEMP_F, UPPER_HOUSE_TEMP_F, goNow, autoMode
    parsed = line.strip().split(" ")
    command = parsed[0]
    #if ord(command[0]) == 239:         doesn't work!!!       # timed out with ?? and user hit enter
    #    return "command done"
    settemp = "62"  # default to avoid reference before setting
    if command == "exit":
        BypassShutdown(myHouseHeating, datacomm)  # check for bypass and request shutoff
        sys.exit()
    if len(parsed) > 1:  # is there the required argument?
        zone = parsed[1]
        if len(parsed) > 2:
            settemp = parsed[2]
    elif command <> "now":  # +/- for zones here, converts the +/- into a set command
        if len(parsed) == 1:
            return "not a command"
        else:
            zone = parsed[0][1]
        command = "set"
        if parsed[0].startswith("+"):  # if +, mimic zone temp cmd to above current
            if zone in validZoneNumbers:
                settemp = str(myHouseHeating.zones[int(zone) - 2].getCurrentTemp() + 0.5)
        elif parsed[0].startswith("-"):  # if -, mimic zone temp cmd to below current
            if zone in validZoneNumbers:
                settemp = str(myHouseHeating.zones[int(zone) - 2].getCurrentTemp() - 0.5)
        else:
            return "No argument"
    if command == "bypass":  # bypass
        if zone == "on":
            datacomm.setBypassOn(myHouseHeating)
        elif zone == "off":
            datacomm.setBypassOff(myHouseHeating)
        else:
            return "argument should be on or off"
    elif command == "set":  # setpoint changes
        try:
            settempF = float(settemp)
        except:
            return "invalid temperature"
        else:
            if zone == "all":
                for temp in myHouseHeating.zones:
                    temp.setSetPoint(settempF)  # all get the same set point
            elif zone in validZoneNumbers and (settempF > LOWER_HOUSE_TEMP_F) and (
                    settempF < UPPER_HOUSE_TEMP_F):  # validate zones and setpoint value
                myHouseHeating.zones[int(zone) - 2].setSetPoint(settempF)  # individual set point
            else:
                return "arguments out of range"
    elif command == "on":
        if zone == "slab" or zone == "s":
            datacomm.setSlabOn(1, myHouseHeating)  # turn slab pump on
        elif zone == "boilerrm" or zone == "b":
            datacomm.setSlabOn(2, myHouseHeating)  # turn boiler room slab pump on
        else:
            return "argument misspelled"
    elif command == "off":
        if zone == "slab" or zone == "s":
            datacomm.setSlabOff(1, myHouseHeating)  # turn slab pump off
        elif zone == "boilerrm" or zone == "b":
            datacomm.setSlabOff(2, myHouseHeating)  # exchanger pump off
        else:
            return "argument is slab or boilerrm"
    elif command == "now":  # cause set points to be checked now, not wait for cycle
        goNow = True
    elif command == "auto":  # auto operation involves phased heat to loops, which limits
        if zone == "on":  # the return of hot water to the tanks New for V4.0
            autoMode = True
            BuildAutoDisplay(win5)
            for zone in myHouseHeating.zones:
                zone.setSetPoint(ZONE_COMFORT[int(zone.getNumber()) - 2])  # set to predefined best values
        elif zone == "off":
            autoMode = False
            win5.clear()
            win5.refresh()
        else:
            return "argument should be on or off"
    else:  # new commands before here
        return "not a command"
    return "command done"


def BypassShutdown(myHouseHeating, datacomm):  # used when exiting to ensure bypass of turned off
    if onBypass:
        win4.addstr(3, 1, "Turn Off bypass? (Y or N) -->")
        win4.timeout(-1)
        command = win4.getch()
        if command == ord("y") or command == ord("Y"):
            datacomm.setBypassOff(myHouseHeating)
            win4.addstr(4, 1, "Bypass turning off", curses.color_pair(3))


def displayHelp(win):
    buildCommandWindow(win)
    win.addstr(1, 1, "syntax : command (arguments)", curses.color_pair(2))
    win.addstr(2, 1, " commands : bypass (on or off)")
    win.addstr(3, 1, "        set (zone# || all) (temp)")
    win.addstr(4, 1, "        + or - (zone#)    ")
    win.addstr(5, 1, "        on or off (Slab || Boilerrm)")
    win.addstr(6, 1, "        now ,    auto on || off     ")
    win.addstr(7, 1, "hit any key to continue")
    win.refresh()
    win.timeout(-1)  # block waiting for read
    ch = win.getch()
    win.timeout(0)  # unblock


def executeSetPoints(datacomm, houseData):
    for zone in houseData.zones:
        if (zone.getCoil() == 0) and (zone.getCurrentTemp() < zone.getSetPoint() - 0.3):  # turn on
            datacomm.setHouseZoneOn(zone.getNumber(), houseData)
        elif (zone.getCoil() == 1) and (zone.getCurrentTemp() > zone.getSetPoint() + 0.3):  # turn on
            datacomm.setHouseZoneOff(zone.getNumber(), houseData)

def needWoodNotify(systemHeat,buffer):
    global OVER_LOW_FLUE, MSG_SENT, FRO_HEATING, LOW_FLUE, win3
    currentFlue = systemHeat.zones[0].getFlue()
    if (currentFlue > LOW_FLUE + 10):                  # OK, it's heated up
        OVER_LOW_FLUE = True
        MSG_SENT = False        
    elif ((currentFlue < LOW_FLUE) and (systemHeat.zones[0].getFrolingStatus() == FRO_HEATING) and
             (OVER_LOW_FLUE) and (not MSG_SENT)):
        OVER_LOW_FLUE = False
        msg = "Froiling Wood Check - Flue temp = " + str(currentFlue) + " Time = " + datetime.now().strftime("%H:%M")
        gm = Gmail('aphouse77@gmail.com', '22Java$$')
        updateMessage(win3, "sent wood load message ", buffer)
        for textNumber in WOOD_TEXT_TO:
            gm.send_message(textNumber,'Froiling Check', msg)
        
def checkSetback(allzones):
    global SETBACK_AMOUNT, SETBACK_END, SETBACK_START, SETBACK_ON, setupTime, ZONE_SETBACK, ZONE_COMFORT
    now = datetime.now()
    setbackTime = now.replace(hour=SETBACK_START, minute=0, second=0, microsecond=0) # late night
    if not SETBACK_ON:
        setupTime = now.replace(hour=SETBACK_END, minute=0, second=0, microsecond=0)
        if SETBACK_START > SETBACK_END:                             # setup is tomorrow
            setupTime = setupTime + timedelta(days=1)               # early morning, next day
    if (now > setbackTime) and not SETBACK_ON:                                      #setback now?
        SETBACK_ON = True                                           # only oak room and den for setback
        allzones.zones[0].setSetPoint(ZONE_SETBACK[0])
        allzones.zones[1].setSetPoint(ZONE_SETBACK[1])
    elif SETBACK_ON and (now > setupTime):                                          #return to daytime
        SETBACK_ON = False
        allzones.zones[0].setSetPoint(ZONE_COMFORT[0])
        allzones.zones[1].setSetPoint(ZONE_COMFORT[1])

#---------------------------------------------------------------------------------
#   Get the lowest temperature for the next 24 hrs (3 hour increments) to display
def getWeatherData():
    global api_key, base_url, complete_url, estLowTemp, estWeather, estLowTime 
    # get method of requests module return response object in json format 
    try:
        response = requests.get(complete_url)
    except:
        logging.info("Weather failed")
        estWeather = "No Data"
    # convert json format data into python format data
    else:
        x = response.json() 
        if x["cod"] != "404":               # 404 is city not found
            y = x["list"]                   # x is dictionary, y is list
            estLowTemp = 100
            for i in range(0,7):            # next 24 hours, find lowest temperature
                if (estLowTemp > pytemperature.k2f(y[i]["main"]["temp"])):
                    estLowTemp = pytemperature.k2f(y[i]["main"]["temp"])   # new low temp
                    lowTime = y[i]["dt_txt"]            # time of low temp
                    index = i
            estWeather = y[index]["weather"][0]["description"]
            parsed = lowTime.strip().split(" ")           # format is "date time"
            estLowTime = (parsed[1])[0:5]                       
		
def getConfig():
    global SET_POINT_RANGE, SETBACK_START, SETBACK_END, SETBACK_AMOUNT 
    global ZONE_COMFORT, END_RETURN_TEMP, MINIMUM_WAIT, MAX_ZONE_TIME
    global LOW_FLUE, WOOD_TEXT_TO, ZONE_SETBACK
    config = ConfigParser.ConfigParser(allow_no_value=True)
    config.read('heat.ini')

    SET_POINT_RANGE = config.getfloat('House', 'SET_POINT_RANGE')
    SETBACK_START = config.getint('House', 'SETBACK_START')
    SETBACK_END = config.getint('House', 'SETBACK_END')
    SETBACK_AMOUNT = config.getfloat('House', 'SETBACK_AMOUNT')
    zoneString = config.get('House', 'ZONE_COMFORT')
    ZONE_COMFORT = [float(i) for i in zoneString.split(',')]    # convert to a float list
    ZONE_SETBACK = [eachZone-SETBACK_AMOUNT for eachZone in ZONE_COMFORT] # calc setback temps and save
    END_RETURN_TEMP = config.getint('AUTO', 'END_RETURN_TEMP')
    maxZoneStr = config.get('AUTO', 'MAX_ZONE_TIME')
    MINIMUM_WAIT = config.getfloat('AUTO', 'MINIMUM_WAIT')
    MAX_ZONE_TIME = [int(i) for i in maxZoneStr.split(',')]    # convert to integer list
    LOW_FLUE = config.getint('System', 'LOW_FLUE')
    woodTextAddrs = config.get('System', 'WOOD_TEXT_TO')
    WOOD_TEXT_TO = woodTextAddrs.split(',')         # convert to a list    
    
def main1(stdscr):
    global goNow, SETBACK_ENABLE
    runMore = True
    stdscr.nodelay(True)
    curses.cbreak()
    near20 = ([19, 0, 1])
    getConfig()
    logging.basicConfig(filename='Production.log', format='%(levelname)s:%(asctime)s %(message)s', level=logging.INFO)
    logging.info("System Starting ")

    myHouseHeating = houseZones()  # instantiate house data object
    myHeatSystem = systemZones()  # instantiate heat producing data object
    defineScreens(stdscr, myHouseHeating)  # put up screen framework
    buffer = messageBuffer()  # allocate message buffer object
    getWeatherData()
    updateMessage(win3, "System is starting", buffer)  # put out first message
    dataMapper = dataReadWrite(myHouseHeating, myHeatSystem, buffer)  # instantiate data collection object & start
    newData = True
    getWeatherTime = datetime.now()
    startTemps = datetime.now()
    startCoils = startTemps
    startLoop = startTemps

    while runMore:
        sleepTime = 1.0
        tempElapseTime = (datetime.now() - startTemps).seconds
        if (tempElapseTime > 5):  # temp every 5 seconds, coils every 30
            updateMessage(win3, "getting temps ", buffer)
            dataMapper.getData(myHouseHeating, myHeatSystem, buffer)  # get updated temp data
            startTemps = datetime.now()
            sleepTime = 0.2
            newData = True
        if (((datetime.now() - getWeatherTime).seconds)/60) > 180:     # get weather every 3 hrs
            getWeatherTime = datetime.now()
            updateMessage(win3, "getting weather", buffer)
            getWeatherData()
        if (datetime.now() - startCoils).seconds > 30:
            sleepTime = 0.05
            updateMessage(win3, "getting coils ", buffer)
            dataMapper.getCoils(myHouseHeating, myHeatSystem, buffer)  # get updated coils
            startCoils = datetime.now()            # reset times
            startTemps = datetime.now()
            newData = True                         # could be new data
            #needWoodNotify(myHeatSystem,buffer)           # check if system needs wood tended
            if SETBACK_ENABLE:
                checkSetback(myHouseHeating)
        runMore = doCommands(win4, myHouseHeating, dataMapper)
        if autoMode and tempElapseTime > 5:  # same timing as temp settings
            if not onBypass:
                ExecCommands("bypass on", myHouseHeating, dataMapper)
            myHouseHeating.DoAutoZoneControl(myHeatSystem.zones[2].getHouse(), dataMapper)
            newData = True
            # don't forget, shutoff when on propane
        if onBypass and not autoMode:
            elapseTime = displayTimer(win4, startLoop)
            if ((elapseTime <= 0) or goNow):
                updateMessage(win3, "Executing setpoint ", buffer)
                executeSetPoints(dataMapper, myHouseHeating)
                startLoop = datetime.now()
                goNow = False
                newData = True
        else:
            startLoop = datetime.now()  # reset so it doesn't overflow
        if newData:
            displayHouseData(win1, myHouseHeating, myHeatSystem)  # lastly, display on screen
            displaySystemData(stdscr, win2, myHeatSystem)
        newData = False
        if runMore:
            sleep(sleepTime)
    curses.nocbreak()
    stdscr.keypad(0)
    curses.echo()
    curses.endwin()


# =============================================================================================
stdscr = curses.initscr()
curses.start_color()
wrapper(main1)  # wrapped for error capture and return to normal recovery
# ==============================================================================================
